from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_openai import AzureChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.prebuilt import create_react_agent
from state import AgentState
import tools
import config
import json

# --- LLM Setup ---
llm = AzureChatOpenAI(azure_deployment=config.AZURE_OPENAI_CHAT_DEPLOYMENT_NAME, 
                        temperature=0, 
                        openai_api_key=config.OPENAI_API_KEY, 
                        api_version=config.OPENAI_API_VERSION, 
                        azure_endpoint=config.AZURE_OPENAI_ENDPOINT)

# --- Supervisor ---
members = ["SharePointAgent", "D365Agent", "EmailAgent", "SearchAgent"]
system_prompt = (
    "You are a supervisor tasked with managing a conversation between the"
    " following workers: {members}. Given the following user request,"
    " respond with the worker to act next. Each worker will perform a"
    " task and respond with their results and status. When finished,"
    " respond with FINISH."
    "\n\n"
    "Logic:"
    "\n1. If the user input is casual (e.g., 'hello', 'how are you'), route to 'SearchAgent' to handle it politely."
    "\n2. If the user is looking for an item, route to 'SearchAgent'."
    "\n3. If the user wants to create a job or send emails, route to 'EmailAgent'."
    "\n4. If the user wants to download/upload sheets, route to 'SharePointAgent'."
    "\n5. If the user wants to check prices in D365, route to 'D365Agent'."
)
options = ["FINISH"] + members
function_def = {
    "name": "route",
    "description": "Select the next role.",
    "parameters": {
        "title": "routeSchema",
        "type": "object",
        "properties": {
            "next": {
                "title": "Next",
                "anyOf": [
                    {"enum": options},
                ],
            }
        },
        "required": ["next"],
    },
}
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        (
            "system",
            "Given the conversation above, who should act next?"
            " Or should we FINISH? Select one of: {options}",
        ),
    ]
).partial(options=str(options), members=", ".join(members))

supervisor_chain = (
    prompt
    | llm.with_structured_output(function_def)
)

def supervisor_node(state: AgentState):
    result = supervisor_chain.invoke(state)
    return {"next": result["next"]}

# --- Search Agent ---
# Explanation: A ReAct agent uses the LLM to 'Reason' about the user input and 'Act' by calling tools.
# It loops (Reason -> Act -> Observe) until it has a final answer.
search_agent = create_react_agent(llm, tools=[tools.search_similar_items])

def search_node(state: AgentState):
    # We invoke the agent with the current state. It returns a dictionary with "messages".
    result = search_agent.invoke(state)
    # We return the update to the state. 
    # Note: create_react_agent automatically handles appending messages to the state history.
    return {"messages": result["messages"]}

# --- Email Agent ---
email_tools = [
    tools.get_vendor_emails,
    tools.save_vendor_email,
    tools.create_sharepoint_job,
    tools.send_email,
    tools.check_email_replies,
    tools.update_sharepoint_job
]
email_agent = create_react_agent(llm, tools=email_tools)

def email_node(state: AgentState):
    result = email_agent.invoke(state)
    return {"messages": result["messages"]}

# --- SharePoint Agent ---
sharepoint_tools = [
    tools.generate_costing_sheet,
    tools.upload_to_sharepoint
]
sharepoint_agent = create_react_agent(llm, tools=sharepoint_tools)

def sharepoint_node(state: AgentState):
    result = sharepoint_agent.invoke(state)
    return {"messages": result["messages"]}

# --- D365 Agent ---
d365_tools = [tools.get_d365_price]
d365_agent = create_react_agent(llm, tools=d365_tools)

def d365_node(state: AgentState):
    result = d365_agent.invoke(state)
    return {"messages": result["messages"]}

