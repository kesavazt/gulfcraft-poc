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
members = ["SearchAgent"]
system_prompt = (
    "You are a supervisor tasked with managing a conversation between the"
    " following workers: {members}. Given the following user request,"
    " respond with the worker to act next. Each worker will perform a"
    " task and respond with their results and status. When finished,"
    " respond with FINISH."
    "\n\n"
    "Logic:"
    "\n1. If the user input is casual (e.g., 'hello', 'how are you'), greet the user back and respond with FINISH"
    "\n2. If the user wants to create a job or is requesting a quotation, route to 'SearchAgent'. Only route if the information is complete. The user query must have a description and boat model(e.g MAJESTY62 etc)"
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
#search_agent = create_react_agent(llm, tools=[tools.search_similar_quotations])



def search_node(state: AgentState):
    user_query = state["messages"][-1].content # Classified by the Supervisor so it's safe hopefully

    # We invoke the agent with the current state. It returns a dictionary with "messages".
    new_state =  [
        ("system",
f"""
The user has asked the following query: {user_query} 

The user wants a job done. He has provided a description and boat model. Extract the description and boat model and
use the search_similar_quotations tool to get a list of similar quotations. When extracting description, don't miss important keywords like fitting,
 leaking, plumbing etc from the description if there are any.
"""),
    ]
    llm_with_tools = llm.bind_tools([tools.search_similar_quotations])
    result = llm_with_tools.invoke(new_state)
    
    # We return the update to the state. 
    # Note: create_react_agent automatically handles appending messages to the state history.
    return {"messages": [result]}#result.content["messages"]}
    
def refinement_node(state: AgentState):
    fetched_quotations = state["messages"][-1].content
    print(state["messages"][-1].content)
    #exit()
    new_state =  [
        ("system",
f'''
Following is a list of quotations:
{fetched_quotations}
Present each of these to the user. Mention all attributes of each quotation. Don't skip anything 
Use bulleted list, don't use numbers when presenting.
Ask the user to select one of these quotations by entering the selected quotation's id.
'''
    )
    ]
    result = llm.invoke(new_state)
    
    return {"messages": [result]}

def costing_sheet_node(state: AgentState):
    selected_quotation = state["selected_quotation"]
    return {"messages": state.messages}
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

