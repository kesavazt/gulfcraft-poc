from langgraph.graph import StateGraph, END
from state import AgentState
from agents import supervisor_node, sharepoint_node, d365_node, email_node, search_node
from database import init_db

# --- Graph Construction ---
workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("Supervisor", supervisor_node)
workflow.add_node("SharePointAgent", sharepoint_node)
workflow.add_node("D365Agent", d365_node)
workflow.add_node("EmailAgent", email_node)
workflow.add_node("SearchAgent", search_node)

# Add Edges
# Start with Supervisor
workflow.set_entry_point("Supervisor")

# Supervisor decides next
workflow.add_conditional_edges(
    "Supervisor",
    lambda x: x["next"],
    {
        "SharePointAgent": "SharePointAgent",
        "D365Agent": "D365Agent",
        "EmailAgent": "EmailAgent",
        "SearchAgent": "SearchAgent",
        "FINISH": END
    }
)

# Agents return to Supervisor
workflow.add_edge("SharePointAgent", "Supervisor")
workflow.add_edge("D365Agent", "Supervisor")
workflow.add_edge("EmailAgent", "Supervisor")
workflow.add_edge("SearchAgent", "Supervisor")

# Compile
app = workflow.compile()

if __name__ == "__main__":
    # Test Run
    from langchain_core.messages import HumanMessage
    inputs = {
        "messages": [HumanMessage(content="Create a job for Marine Plywood and check the price")],
        "user_id": 1,
        "threshold": 1000.0
    }
    for output in app.stream(inputs):
        for key, value in output.items():
            print(f"--- {key} ---")
            print(value)
