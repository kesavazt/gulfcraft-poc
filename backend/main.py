from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from state import AgentState
from agents import supervisor_node, sharepoint_node, email_node, search_node,refinement_node,costing_sheet_node
from tools import search_similar_quotations
from database import init_db

# --- Graph Construction ---
workflow = StateGraph(AgentState)
tool_node = ToolNode([search_similar_quotations])
# Add Nodes
workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("SearchAgent", search_node) # searches for quotation_lines
workflow.add_node('Tools',tool_node)
workflow.add_node("RefinementAgent",refinement_node) 
workflow.add_node("CostingSheetAgent",costing_sheet_node) # handles sending emails, creating costing sheet and uploading to sharepoint



# Add Edges
# Start with Supervisor
workflow.set_entry_point("Supervisor")

# Supervisor decides next
workflow.add_conditional_edges(
    "Supervisor",
    lambda x: x["next"],
    {
        "SearchAgent": "SearchAgent",
        "Supervisor": "Supervisor",
        "FINISH": END
    }
)

# Agents return to Supervisor
workflow.add_edge("CostingSheetAgent", "Supervisor")
workflow.add_edge("SearchAgent","Tools")
workflow.add_edge("Tools","RefinementAgent")
workflow.add_edge("RefinementAgent",END)#"CostingSheetAgent")
workflow.add_edge("CostingSheetAgent",END)
# Compile
app = workflow.compile()

if __name__ == "__main__":
    # Test Run
    from langchain_core.messages import HumanMessage
    inputs = {
        "messages": [HumanMessage(content="Give me a quotation for boat polishing. My boat model is MAJESTY62")],
        "user_id": 1,
        "threshold": 1000.0
    }
    # Workflow :
    # 1) Give a list of quotation_lines that are relevant to this
    # 2) The user selects one of these or asks for more
    # 3) Create a costing sheet and add all the items having prices less 1000 dirhams (for the remaining it sends an email to vinod)
    # 4) Listen for the incoming emails and look for price quotations (Mistral OCR model to extract price items) and update the costing sheet
    # 5) Upload the costing sheet to sharepoint and ask the user to check
    '''inputs = {
        "messages": [HumanMessage(content="Find me an item with the following description:\n'High quality fog horn for marine use. Specification 3.'")],
        "user_id": 1,
        "threshold": 1000.0
    }'''
    for output in app.stream(inputs):
        for key, value in output.items():
            print(f"--- {key} ---")
            if 'messages' in value:
                for msg in value["messages"]:
                    if isinstance(msg,list):
                        print(msg)
                    else:
                        print(msg.content)
            else:
                print(value)
