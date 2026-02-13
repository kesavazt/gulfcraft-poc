"""
Supervisor Agent Node

Routes user requests to appropriate worker agents based on intent.
Enhanced with confidence scoring and correction detection.
"""

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, HumanMessage
from core.state import AgentState
from utils.llm import llm
from utils.prompts import SUPERVISOR_SYSTEM_PROMPT
from utils import tools
from utils.langfuse_tracing import trace_agent
from utils.intent_scorer import IntentConfidenceScorer
from utils.correction_detector import CorrectionDetector
from utils.handoff import AgentHandoff
from utils.delegation import AgentDelegation
from utils.transition_logger import TransitionLogger
from utils.conversation_repair import ConversationRepair


# --- Supervisor Configuration ---

# CostingAgent is not directly routable from Supervisor - only via SelectionAgent
ROUTABLE_MEMBERS = [
    "SearchAgent",
    "SelectionAgent",
    "StatusAgent",
    "EditJobAgent",
    "QuoteManagementAgent",
    "JobLifecycleAgent",
    "PricingAdvisorAgent",
    "ExplainerAgent",
    "VendorInfoAgent"
]
OPTIONS = ["FINISH"] + ROUTABLE_MEMBERS

ROUTE_FUNCTION_DEF = {
    "name": "route",
    "description": "Select the next role.",
    "parameters": {
        "title": "routeSchema",
        "type": "object",
        "properties": {
            "next": {
                "title": "Next",
                "anyOf": [{"enum": OPTIONS}],
            },
            "greeting_response": {
                "title": "GreetingResponse",
                "type": "string",
                "description": "Response to the user when no worker is selected (e.g., greetings, asking for missing information)"
            }
        },
        "required": ["next"],
    },
}

# Build the supervisor chain
_prompt = ChatPromptTemplate.from_messages([
    ("system", SUPERVISOR_SYSTEM_PROMPT),
    MessagesPlaceholder(variable_name="messages"),
    ("system", "Given the conversation above, who should act next? Or should we FINISH? Select one of: {options}"),
]).partial(options=str(OPTIONS), members=", ".join(ROUTABLE_MEMBERS))

_supervisor_chain = _prompt | llm.with_structured_output(ROUTE_FUNCTION_DEF)


@trace_agent
def supervisor_node(state: AgentState):
    """
    Supervisor node that routes user requests to appropriate worker agents.
    Enhanced with intent confidence scoring and correction detection.

    Returns:
        dict with 'next' key indicating the next agent, and optionally 'messages' for greetings.
    """
    # Check if there's a pending disambiguation/interactive flow
    # If so, route back to the same agent without re-evaluating intent
    pending = state.get("pending_disambiguation")
    if pending and pending.get("agent"):
        # Handle delegation confirmation
        if pending.get("disambiguation_type") == "delegation_confirm":
            delegation = AgentDelegation()
            user_response = state.get("messages", [])[-1].content if state.get("messages") else ""
            result = delegation.handle_delegation_response(user_response, pending)
            return result

        # Regular disambiguation routing
        agent_map = {
            "edit_job": "EditJobAgent",
            "quote_management": "QuoteManagementAgent",
            "pricing_advisor": "PricingAdvisorAgent",
        }
        agent_name = agent_map.get(pending["agent"])
        if agent_name:
            return {"next": agent_name}

    # Get user's message
    messages = state.get("messages", [])
    user_message = ""
    if messages and isinstance(messages[-1], HumanMessage):
        user_message = messages[-1].content

    # Check for conversation breakdown first (highest priority)
    repair = ConversationRepair()
    if repair.detect_breakdown(messages, state):
        print("[Supervisor] Conversation breakdown detected - initiating repair")
        return repair.repair_strategy(messages, state)

    # Check for user corrections
    correction_detector = CorrectionDetector()
    correction = correction_detector.detect_correction(
        user_message,
        messages,
        state.get("last_agent")
    )

    if correction and correction["is_correction"]:
        print(f"[Supervisor] Detected correction: {correction['correction_type']}")
        # Store correction for learning
        if state.get("user_id"):
            correction_detector.store_correction(
                user_id=state["user_id"],
                conversation_id=state.get("conversation_id", "unknown"),
                original_input=correction["original_input"],
                extracted_intent=correction["last_agent"] or "unknown",
                corrected_intent="user_correction",  # Will be updated based on new routing
                correction_type=correction["correction_type"]
            )

    trace_input = {"messages_count": len(messages)}
    try:
        result = _supervisor_chain.invoke(state)
    except Exception as e:
        raise

    routed_agent = result["next"]

    # Score routing confidence (skip for FINISH)
    if routed_agent != "FINISH":
        scorer = IntentConfidenceScorer()
        confidence_score = scorer.score_intent(
            user_message=user_message,
            routed_agent=routed_agent,
            conversation_history=messages,
            last_action=state.get("last_action"),
            last_agent=state.get("last_agent")
        )

        print(f"[Supervisor] Routing to {routed_agent} with confidence {confidence_score['confidence']} ({confidence_score['threshold']})")

        # Prepare handoff and routing metadata
        last_agent = state.get("last_agent")
        handoff = AgentHandoff()
        handoff_context = handoff.prepare_handoff_context(state, routed_agent)

        # Determine routing reason
        if state.get("delegation_source"):
            routing_reason = "delegation_accepted"
        elif pending:
            routing_reason = "pending_disambiguation"
        else:
            routing_reason = "user_requested"

        # Build transition record
        transition_history = state.get("transition_history", [])
        transition_record = handoff.build_transition_record(
            last_agent,
            routed_agent,
            routing_reason,
            handoff_context
        )
        transition_history.append(transition_record)

        # Log transition to database
        conversation_id = state.get("conversation_id", "unknown")
        if conversation_id != "unknown":
            logger = TransitionLogger()
            logger.log_transition(
                conversation_id=conversation_id,
                from_agent=last_agent,
                to_agent=routed_agent,
                routing_reason=routing_reason
            )

        # Generate handoff message if transitioning between agents
        handoff_messages = []
        if handoff.should_show_handoff(last_agent, routed_agent):
            handoff_msg = handoff.create_handoff_message(last_agent, routed_agent, handoff_context)
            handoff_messages.append(AIMessage(content=handoff_msg))

        # Build routing result with metadata
        routing_result = {
            "next": routed_agent,
            "intent_confidence": confidence_score["confidence"],
            "last_agent": routed_agent,
            "routing_reason": routing_reason,
            "routing_context": handoff_context,
            "transition_history": transition_history,
            "handoff_context": handoff_context
        }

        # Handle based on confidence threshold
        if confidence_score["threshold"] == "medium":
            # Add clarification message for medium confidence
            clarification = scorer.generate_clarification_message(routed_agent, user_message)
            routing_result["clarification_needed"] = True
            routing_result["messages"] = [AIMessage(content=clarification)] + handoff_messages
            return routing_result
        elif confidence_score["threshold"] == "low":
            # Low confidence - ask user to clarify or rephrase
            return {
                "next": "FINISH",
                "intent_confidence": confidence_score["confidence"],
                "messages": [AIMessage(content=(
                    "I'm not sure I understand what you need. Could you please rephrase your request or provide more details? "
                    "For example:\n"
                    "- 'I need a quotation for polishing. My boat is MAJESTY62'\n"
                    "- 'Show me the status of job COST-12345678'\n"
                    "- 'Add a hydraulic pump to my job'"
                ))],
                "transition_history": transition_history
            }
        else:
            # High confidence - proceed normally with handoff message
            if handoff_messages:
                routing_result["messages"] = handoff_messages
            return routing_result
    else:
        # FINISH route (greetings, etc.)
        if result.get("greeting_response"):
            return {
                "next": result["next"],
                "messages": [AIMessage(content=result["greeting_response"])]
            }

        return {"next": result["next"]}
