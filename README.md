# AI Costing Assistant

An intelligent agent for automating costing workflows, integrated with SharePoint, D365, and Email.

## Project Structure

- `backend/`: FastAPI application and LangGraph agent logic.
- `frontend/`: React application for user interaction.
- `requirements.txt`: Python dependencies.
- `.env.example`: Environment variables template.

## Getting Started

### Backend

1.  Navigate to `backend/`:
    ```bash
    cd backend
    ```
2.  Install dependencies:
    ```bash
    pip install -r ../requirements.txt
    ```
3.  Run the server:
    ```bash
    uvicorn api:app --reload
    ```

### Frontend

1.  Navigate to `frontend/`:
    ```bash
    cd frontend
    ```
2.  Install dependencies:
    ```bash
    npm install
    ```
3.  Run the dev server:
    ```bash
    npm run dev
    ```

## Documentation

See `walkthrough.md` and `deployment.md` in the artifacts folder for detailed guides.
