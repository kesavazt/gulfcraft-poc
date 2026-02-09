"""
PDF Table Extractor
Extracts line items, prices, and quantities from tables in PDF documents
using Mistral Document AI (mistral-document-ai-2505) deployed on Azure for OCR,
and Azure OpenAI for structured extraction.
"""
import os
import sys
import base64
import json
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure backend package is discoverable when run as a script
BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core import config

# Azure-deployed Mistral Document AI model
MISTRAL_DOCUMENT_MODEL = "mistral-document-ai-2505"

# Azure OpenAI config for structured extraction
AZURE_OPENAI_API_VERSION = "2024-08-01-preview"


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text content from a PDF using Mistral Document AI OCR on Azure.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Extracted text content as markdown
    """
    with open(pdf_path, "rb") as f:
        pdf_content = base64.b64encode(f.read()).decode("utf-8")

    endpoint = config.AZURE_MISTRAL_ENDPOINT.rstrip("/")
    url = f"{endpoint}/providers/mistral/azure/ocr"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.AZURE_MISTRAL_API_KEY}"
    }

    payload = {
        "model": MISTRAL_DOCUMENT_MODEL,
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{pdf_content}"
        },
        "include_image_base64": True
    }

    response = requests.post(url, headers=headers, json=payload, timeout=120)

    if response.status_code != 200:
        print(f"[PDF Extractor] OCR API Error: {response.status_code}")
        print(f"[PDF Extractor] Response: {response.text}")
        return ""

    result = response.json()

    # Extract text from all pages
    text_parts = []
    if "pages" in result:
        for page in result["pages"]:
            if "markdown" in page:
                text_parts.append(page["markdown"])

    return "\n\n".join(text_parts)


def extract_line_items_from_text(text: str) -> List[Dict[str, Any]]:
    """
    Extract line items from OCR text using Azure OpenAI chat model.

    Args:
        text: OCR extracted text

    Returns:
        List of line item dictionaries
    """
    extraction_prompt = f"""Analyze the following document text and extract ALL line items from any tables present.

Document text:
{text}

For each line item, extract:
1. item_name: The product/service name or description
2. quantity: The quantity (as a number, default to 1 if not specified)
3. unit_price: The unit price (as a number without currency symbols)
4. total_price: The total price for this line item (as a number, or null if not shown)

Return the data as a JSON array with this exact format:
[
    {{
        "item_name": "Product or service description",
        "quantity": 2,
        "unit_price": 150.00,
        "total_price": 300.00
    }}
]

Important:
- Extract ALL items from any tables, not just a sample
- Convert all prices to numbers (remove currency symbols like $, AED, USD)
- If quantity is not specified, assume 1
- If total_price is not shown, set it to null
- Include item codes/SKUs in the item_name if present
- Return ONLY the JSON array, no additional text"""

    endpoint = config.AZURE_OPENAI_ENDPOINT.rstrip("/")
    deployment = config.AZURE_OPENAI_CHAT_DEPLOYMENT_NAME
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"

    headers = {
        "Content-Type": "application/json",
        "api-key": config.AZURE_OPENAI_API_KEY
    }

    payload = {
        "messages": [
            {
                "role": "user",
                "content": extraction_prompt
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload, timeout=120)

    if response.status_code != 200:
        print(f"[PDF Extractor] Chat API Error: {response.status_code}")
        print(f"[PDF Extractor] Response: {response.text}")
        return []

    result = response.json()
    content = result["choices"][0]["message"]["content"]

    return parse_json_response(content)


def extract_line_items_from_pdf(pdf_path: str) -> List[Dict[str, Any]]:
    """
    Extract line items with prices and quantities from a PDF document.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of dictionaries containing:
        - item_name: Name/description of the item
        - quantity: Quantity of items
        - unit_price: Price per unit
        - total_price: Total price for the line (if available)
    """
    if not os.path.exists(pdf_path):
        print(f"[Error] File not found: {pdf_path}")
        return []

    if not config.AZURE_MISTRAL_ENDPOINT or not config.AZURE_MISTRAL_API_KEY:
        print("[Error] AZURE_MISTRAL_ENDPOINT and AZURE_MISTRAL_API_KEY must be configured in .env")
        return []

    print(f"[PDF Extractor] Processing: {pdf_path}")

    try:
        file_size = os.path.getsize(pdf_path) / 1024  # KB
        print(f"[PDF Extractor] File size: {file_size:.1f} KB")

        # Step 1: Extract text using Mistral Document AI OCR
        print(f"[PDF Extractor] Sending to Mistral Document AI ({MISTRAL_DOCUMENT_MODEL})...")
        ocr_text = extract_text_from_pdf(pdf_path)

        if not ocr_text:
            print("[PDF Extractor] Failed to extract text from PDF")
            return []

        print(f"[PDF Extractor] OCR extracted {len(ocr_text)} chars")

        # Step 2: Extract structured line items from text using Azure OpenAI
        deployment = config.AZURE_OPENAI_CHAT_DEPLOYMENT_NAME
        print(f"[PDF Extractor] Extracting line items ({deployment})...")
        line_items = extract_line_items_from_text(ocr_text)

        if line_items:
            print(f"[PDF Extractor] Extracted {len(line_items)} line items")
        else:
            print("[PDF Extractor] No line items extracted")
            print(f"[PDF Extractor] OCR text preview: {ocr_text[:500]}...")

        return line_items

    except requests.exceptions.Timeout:
        print("[PDF Extractor] Error: Request timed out")
        return []
    except requests.exceptions.RequestException as e:
        print(f"[PDF Extractor] Request Error: {e}")
        return []
    except Exception as e:
        print(f"[PDF Extractor] Error: {e}")
        return []


def parse_json_response(content: str) -> List[Dict[str, Any]]:
    """Parse JSON array from model response."""
    try:
        # Try to find JSON array in response
        start = content.find("[")
        end = content.rfind("]") + 1

        if start >= 0 and end > start:
            json_str = content[start:end]
            items = json.loads(json_str)

            # Validate and clean up items
            cleaned_items = []
            for item in items:
                cleaned_item = {
                    "item_name": str(item.get("item_name", "Unknown")).strip(),
                    "quantity": parse_number(item.get("quantity", 1), default=1),
                    "unit_price": parse_number(item.get("unit_price", 0), default=0),
                    "total_price": parse_number(item.get("total_price"), default=None)
                }

                # Calculate total if not provided
                if cleaned_item["total_price"] is None and cleaned_item["unit_price"]:
                    cleaned_item["total_price"] = round(
                        cleaned_item["quantity"] * cleaned_item["unit_price"], 2
                    )

                cleaned_items.append(cleaned_item)

            return cleaned_items

    except json.JSONDecodeError as e:
        print(f"[PDF Extractor] JSON parse error: {e}")

    return []


def parse_number(value: Any, default: Any = None) -> Optional[float]:
    """Parse a number from various formats."""
    if value is None:
        return default

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        # Remove currency symbols and commas
        cleaned = value.replace("$", "").replace(",", "").replace(" ", "")
        cleaned = cleaned.replace("AED", "").replace("USD", "").replace("SAR", "")
        cleaned = cleaned.strip()

        try:
            return float(cleaned)
        except ValueError:
            return default

    return default


def print_line_items(items: List[Dict[str, Any]]):
    """Pretty print extracted line items."""
    if not items:
        print("\nNo line items to display.")
        return

    print("\n" + "=" * 80)
    print(f"{'#':<4} {'Item Name':<40} {'Qty':<8} {'Unit Price':<12} {'Total':<12}")
    print("=" * 80)

    grand_total = 0
    for i, item in enumerate(items, 1):
        name = item["item_name"][:38] + ".." if len(item["item_name"]) > 40 else item["item_name"]
        qty = item["quantity"]
        unit = item["unit_price"]
        total = item["total_price"]

        if total:
            grand_total += total

        print(f"{i:<4} {name:<40} {qty:<8} {unit:<12.2f} {total if total else 'N/A':<12}")

    print("-" * 80)
    print(f"{'GRAND TOTAL':<52} {'':<8} {'':<12} {grand_total:<12.2f}")
    print("=" * 80)


def save_to_json(items: List[Dict[str, Any]], output_path: str):
    """Save extracted items to a JSON file."""
    with open(output_path, "w") as f:
        json.dump(items, f, indent=2)
    print(f"\n[PDF Extractor] Saved to: {output_path}")


def save_to_csv(items: List[Dict[str, Any]], output_path: str):
    """Save extracted items to a CSV file."""
    import csv

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["item_name", "quantity", "unit_price", "total_price"])
        writer.writeheader()
        writer.writerows(items)

    print(f"[PDF Extractor] Saved to: {output_path}")


def main():
    """Main entry point for CLI usage."""
    if len(sys.argv) < 2:
        print("PDF Table Extractor - Extract line items from PDF invoices/quotations")
        print("\nUsage:")
        print("  python pdf_extractor.py <pdf_file> [output_format]")
        print("\nArguments:")
        print("  pdf_file       Path to the PDF file to process")
        print("  output_format  Optional: 'json' or 'csv' to save output (default: print only)")
        print("\nExamples:")
        print("  python pdf_extractor.py invoice.pdf")
        print("  python pdf_extractor.py quotation.pdf json")
        print("  python pdf_extractor.py order.pdf csv")
        return

    pdf_path = sys.argv[1]
    output_format = sys.argv[2].lower() if len(sys.argv) > 2 else None

    # Extract line items
    items = extract_line_items_from_pdf(pdf_path)

    # Display results
    print_line_items(items)

    # Save if requested
    if output_format and items:
        base_name = os.path.splitext(pdf_path)[0]

        if output_format == "json":
            save_to_json(items, f"{base_name}_extracted.json")
        elif output_format == "csv":
            save_to_csv(items, f"{base_name}_extracted.csv")
        else:
            print(f"\n[Warning] Unknown format '{output_format}'. Use 'json' or 'csv'.")


if __name__ == "__main__":
    main()
