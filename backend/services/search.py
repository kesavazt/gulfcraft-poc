from typing import List, Dict, Any
from sqlalchemy.orm import Session
from core.database import SessionLocal, Product, QuotationLines
from langchain_openai import OpenAIEmbeddings, AzureOpenAIEmbeddings
from core import config
from sqlalchemy import text, func, desc
# Initialize Embeddings
if config.OPENAI_API_TYPE == "azure":
    embeddings = AzureOpenAIEmbeddings(
        azure_deployment=config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME,
        openai_api_version=config.OPENAI_API_VERSION,
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.OPENAI_API_KEY,
    )
else:
    embeddings = OpenAIEmbeddings(model=config.EMBEDDING_MODEL, openai_api_key=config.OPENAI_API_KEY)

def get_embedding(text: str) -> List[float]:
    # Mock embedding if API key is mock
    if config.OPENAI_API_KEY == "mock_openai_key":
        return [0.1] * 1536
    return embeddings.embed_query(text)

def hybrid_search(query: str,boat_model: str, top_k: int = config.TOP_K_ITEMS) -> List[Dict[str, Any]]:
    session: Session = SessionLocal()
    results = []
    try:
        query_vec = get_embedding(query)
        
        # PGVector cosine distance search
        # Note: This assumes the vector extension is enabled and the column is set up
        # For SQLite dev, this might fail if not handled, so we'll add a fallback or mock
        
        # Normalize boat model for matching (remove spaces, uppercase)
        normalized_boat_model = boat_model.replace(" ", "").upper()
        print(f"DEBUG: hybrid_search called with query='{query}', boat_model='{boat_model}' (normalized='{normalized_boat_model}')")
        
        # Postgres Vector Search
        #results = session.query(Product).order_by(
        #    Product.embedding.cosine_distance(query_vec)
        #).limit(top_k).all()
        # Full Hybrid Search
        semantic = (
            session.query(
                QuotationLines.id,
                (1 - QuotationLines.embedding.cosine_distance(query_vec)).label("semantic_score")
            )
        .filter(func.replace(QuotationLines.afz_boat_model_id, ' ', '') == normalized_boat_model)
        .order_by(QuotationLines.embedding.cosine_distance(query_vec))
        .subquery()
        )


        results = (
            session.query(
            QuotationLines,
            (
                0.7 * semantic.c.semantic_score +
                0.3 * func.coalesce(
                    func.ts_rank(
                        QuotationLines.tsv,
                        func.plainto_tsquery("english", query)
                    ),
                    0
                )
            ).label("score")
        )
        .join(semantic, QuotationLines.id == semantic.c.id)
        .order_by(desc("score"))
        .limit(top_k)
        .all()
        )

        # Returns QuotationID
        return [
            {
                "id": p[0].id,
                "quotation_id": p[0].quotation_id,
                "description": p[0].description,
                "boat_model": p[0].afz_boat_model_id,
                "price": p[0].sales_price,
                "line_num": p[0].line_num
            }
            for p in results
        ]
    except Exception as e:
        print(f"Search Error: {e}")
        return []
    finally:
        session.close()
