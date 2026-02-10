"""Quick test of PDF extractor OCR pipeline."""
from services.pdf_extractor import extract_line_items_from_pdf, print_line_items

pdf_path = r"c:\Users\PC\Downloads\Invoice 3.pdf"
print(f"Testing with: {pdf_path}")
items = extract_line_items_from_pdf(pdf_path)
print_line_items(items)
