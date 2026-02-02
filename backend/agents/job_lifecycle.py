"""
Job Lifecycle Agent Node

Handles job lifecycle operations: approve, download, duplicate, cancel, and email sending.
"""

import json
import re
from langchain_core.messages import AIMessage
from core.state import AgentState
from utils import tools
from utils.llm import llm
from utils.prompts import JOB_LIFECYCLE_AGENT_SYSTEM_PROMPT, JOB_LIFECYCLE_EXTRACTION_PROMPT
from utils.langfuse_tracing import trace_agent


def _extract_lifecycle_parameters(user_message: str, state: AgentState) -> dict:
    """Extract lifecycle operation parameters from user message using LLM."""
    last_job_id = state.get("last_mentioned_job_id") or state.get("job_id") or "Not specified"
    user_id = state.get("user_id", 1)

    prompt = JOB_LIFECYCLE_EXTRACTION_PROMPT.format(
        user_message=user_message,
        last_job_id=last_job_id,
        user_id=user_id
    )

    try:
        response = llm.invoke([{"role": "user", "content": prompt}])
        content = response.content

        # Extract JSON from markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        params = json.loads(content)

        # Use context if job_id not provided
        if not params.get("job_id") and last_job_id != "Not specified":
            params["job_id"] = last_job_id

        return params
    except Exception as e:
        print(f"[JobLifecycleAgent] Extraction error: {e}")
        return {}


@trace_agent
def job_lifecycle_node(state: AgentState):
    """
    Handles job lifecycle operations.
    """
    user_message = state["messages"][-1].content if state.get("messages") else ""
    user_id = state.get("user_id", 1)

    # Extract parameters
    params = _extract_lifecycle_parameters(user_message, state)

    if not params or not params.get("operation"):
        return {
            "messages": [AIMessage(content=
                "I can help you manage job lifecycle! I can:\n\n"
                "✅ **Approve jobs** - Mark jobs as approved\n"
                "📥 **Download costing sheets** - Get download links\n"
                "📋 **Duplicate jobs** - Create copies with modifications\n"
                "❌ **Cancel jobs** - Mark jobs as cancelled\n"
                "📧 **Email costing sheets** - Send to reviewers\n\n"
                "Examples:\n"
                "- 'Approve job COST-00123'\n"
                "- 'Download the costing sheet'\n"
                "- 'Duplicate this job for Nomad 75'\n"
                "- 'Send the costing sheet to manager@gulfcraft.com'"
            )]
        }

    job_id = params.get("job_id")
    operation = params.get("operation")

    if not job_id:
        return {
            "messages": [AIMessage(content=
                "I need to know which job to work with. Please provide a job ID "
                "(e.g., COST-00123456) or mention 'this job' if we were just discussing one."
            )]
        }

    # Execute the appropriate operation
    result = None
    response_msg = ""

    if operation == "approve":
        result = tools.approve_costing_job(job_id=job_id, user_id=user_id)

        if result.get("success"):
            response_msg = (
                f"✅ **Job {job_id} has been approved!**\n\n"
                f"Status updated to: **Approved**\n"
                f"SharePoint has been updated accordingly.\n\n"
                f"Would you like to:\n"
                f"- Download the costing sheet?\n"
                f"- Email it to a reviewer?\n"
                f"- Move on to another job?"
            )
        else:
            response_msg = f"❌ Failed to approve job: {result.get('error', 'Unknown error')}"

    elif operation == "download":
        result = tools.get_download_url(job_id=job_id)

        if result.get("success"):
            response_msg = (
                f"📥 **Costing sheet ready for download!**\n\n"
                f"Job ID: {job_id}\n"
                f"File: {result.get('filename')}\n"
                f"Download URL: {result.get('download_url')}\n\n"
                f"You can access the file from the Requests tab or use the URL above."
            )
        else:
            response_msg = f"❌ {result.get('error', 'Download URL not available')}"

    elif operation == "duplicate":
        new_description = params.get("new_description")
        result = tools.duplicate_costing_job(
            job_id=job_id,
            user_id=user_id,
            new_description=new_description
        )

        if result.get("success"):
            response_msg = (
                f"✅ **Job duplicated successfully!**\n\n"
                f"Original Job: {job_id}\n"
                f"New Job: **{result.get('new_job_id')}**\n"
                f"Items Copied: {result.get('items_copied')}\n\n"
                f"The new job has been created with all line items from the original. "
                f"You can now modify it as needed."
            )
        else:
            response_msg = f"❌ Failed to duplicate job: {result.get('error', 'Unknown error')}"

    elif operation == "cancel":
        result = tools.cancel_costing_job(job_id=job_id, user_id=user_id)

        if result.get("success"):
            response_msg = (
                f"✅ **Job {job_id} has been cancelled**\n\n"
                f"Status updated to: **Cancelled**\n"
                f"SharePoint has been updated accordingly.\n\n"
                f"Note: You can still view this job, but it's marked as cancelled."
            )
        else:
            response_msg = f"❌ Failed to cancel job: {result.get('error', 'Unknown error')}"

    elif operation == "send_email":
        recipient_email = params.get("recipient_email")
        message = params.get("message", "")

        if not recipient_email:
            response_msg = (
                "To send the costing sheet via email, I need the recipient's email address.\n\n"
                "Example: 'Send the costing sheet to manager@gulfcraft.com'"
            )
        else:
            result = tools.send_costing_sheet_email(
                job_id=job_id,
                recipient_email=recipient_email,
                message=message
            )

            if result.get("success"):
                response_msg = (
                    f"✅ **Costing sheet sent successfully!**\n\n"
                    f"Job ID: {job_id}\n"
                    f"Sent to: {recipient_email}\n\n"
                    f"The recipient will receive the Excel costing sheet as an attachment."
                )
            else:
                response_msg = f"❌ Failed to send email: {result.get('error', 'Unknown error')}"

    else:
        response_msg = (
            f"I don't understand the operation '{operation}'. "
            f"I can help with: approve, download, duplicate, cancel, or send_email."
        )

    # Update state with context
    return {
        "messages": [AIMessage(content=response_msg)],
        "last_mentioned_job_id": job_id,
        "last_action": operation
    }
