"""
Search and Refinement Agent Nodes

Handles searching for similar quotations and presenting results to the user.
"""

from langchain_core.messages import AIMessage
from core.state import AgentState
from utils.llm import llm
from utils.prompts import SEARCH_EXTRACTION_PROMPT, REFINEMENT_PROMPT
from utils import tools
from core import config
import json
import ast


def search_node(state: AgentState):
    """
    Searches for similar quotations based on user's job description and boat model.
    
    Handles both new searches and "show more" requests.
    """
    user_query = state["messages"][-1].content

    # Check if this is a "show more" request
    show_more_phrases = ["more quotation", "show more", "see more", "other quotation", "different quotation"]
    is_show_more = any(phrase in user_query.lower() for phrase in show_more_phrases)

    # Get previous search parameters if available
    last_description = state.get("last_search_description")
    last_boat_model = state.get("last_search_boat_model")
    current_top_k = state.get("current_top_k", config.TOP_K_ITEMS)

    if is_show_more and last_description and last_boat_model:
        # Increase top_k and use previous search parameters
        new_top_k = current_top_k + 5
        search_results = tools.search_similar_quotations(last_description, last_boat_model, top_k=new_top_k)

        result_content = str(search_results) if search_results else "No additional quotations found."

        return {
            "messages": [AIMessage(content=result_content)],
            "current_top_k": new_top_k,
            "selected_quotation": None
        }
    else:
        # Extract description and boat model using LLM for new search
        extraction_prompt = [("system", SEARCH_EXTRACTION_PROMPT.format(user_query=user_query))]
        llm_with_tools = llm.bind_tools([tools.search_similar_quotations])
        result = llm_with_tools.invoke(extraction_prompt)

        # Extract parameters from tool call for future "show more" requests
        new_description = None
        new_boat_model = None
        if result.tool_calls:
            for tool_call in result.tool_calls:
                if tool_call.get("name") == "search_similar_quotations":
                    args = tool_call.get("args", {})
                    new_description = args.get("job_description")
                    new_boat_model = args.get("boat_model")
                    break

        return {
            "messages": [result],
            "last_search_description": new_description,
            "last_search_boat_model": new_boat_model,
            "current_top_k": config.TOP_K_ITEMS,
            "selected_quotation": None,
            "job_id": None,
            "generated_file": None,
            "awaiting_selection": False
        }


def refinement_node(state: AgentState):
    """
    Presents search results to user and asks for selection.
    
    Parses the tool output and stores structured quotation data in state.
    """
    messages = state.get("messages", [])

    # Find the tool message with search results
    fetched_quotations = ""
    for msg in reversed(messages):
        if hasattr(msg, 'content') and msg.content:
            fetched_quotations = msg.content
            break

    if not fetched_quotations:
        return {
            "messages": [AIMessage(content="I couldn't find any quotations. Please try again with a different description or boat model.")],
            "awaiting_selection": False
        }

    # Parse quotations string into a list
    parsed_quotations = []
    try:
        try:
            parsed_quotations = json.loads(fetched_quotations)
        except json.JSONDecodeError:
            parsed_quotations = ast.literal_eval(fetched_quotations)
        
        if not isinstance(parsed_quotations, list):
            parsed_quotations = []
    except Exception as e:
        print(f"Error parsing quotations: {e}")
        parsed_quotations = []

    # Generate presentation message
    presentation_prompt = [("system", REFINEMENT_PROMPT.format(count=len(parsed_quotations)))]
    result = llm.invoke(presentation_prompt)

    return {
        "messages": [result],
        "awaiting_selection": True,
        "similar_quotations": parsed_quotations
    }
