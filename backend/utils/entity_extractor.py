"""
Entity Extractor

Multi-strategy entity extraction:
1. Regex patterns for structured entities (job IDs, prices, emails, quantities)
2. spaCy NER for product names and vendor names
3. LLM extraction as fallback for complex entities
"""

import re
from typing import Dict, Any, List, Optional
from utils.llm import llm


class EntityExtractor:
    """
    Multi-strategy entity extraction with confidence scoring.

    Strategies (in order):
    1. Regex patterns - Fast, high confidence for structured data
    2. spaCy NER - Medium speed, good for named entities
    3. LLM extraction - Slower, fallback for complex entities
    """

    # Regex patterns for common entities
    PATTERNS = {
        "job_id": r"COST-[A-Z0-9]{8}",
        "quotation_id": r"AJMFQ-\d{6}",
        "quotation_line": r"(AJMFQ-\d{6}):(\d+)",  # quotation_id:line_num
        "price": r"(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:AED|aed|dirhams?)?",
        "quantity": r"(\d+)\s*(?:units?|pieces?|pcs?|meters?|m\b|items?)?",
        "email": r"[\w\.-]+@[\w\.-]+\.\w+",
        "boat_model": r"MAJESTY\s*\d+|NOMAD\s*\d+|SILVERCAT\s*\d+|NA",
        "number_selection": r"^\s*(\d+)\s*$"  # Simple number (1, 2, 3, etc.)
    }

    def __init__(self):
        """Initialize EntityExtractor with spaCy model (lazy loaded)."""
        self._nlp = None  # Lazy load spaCy to avoid startup delay

    @property
    def nlp(self):
        """Lazy load spaCy NER model."""
        if self._nlp is None:
            try:
                import spacy
                # Load small English model (fast, good for NER)
                self._nlp = spacy.load("en_core_web_sm")
                print("[EntityExtractor] spaCy model loaded successfully")
            except (ImportError, OSError) as e:
                print(f"[EntityExtractor] Warning: spaCy not available - {e}")
                print("[EntityExtractor] Install with: pip install spacy && python -m spacy download en_core_web_sm")
                self._nlp = None
        return self._nlp

    def extract_all(self, text: str) -> Dict[str, Any]:
        """
        Extract all entities from text using multi-strategy approach.

        Args:
            text: Input text

        Returns:
            dict: Extracted entities with confidence scores
                {
                    "job_id": {"value": "COST-12345678", "confidence": 1.0, "method": "regex"},
                    "price": {"value": 1500.0, "confidence": 0.95, "method": "regex"},
                    "product_names": [{"value": "hydraulic pump", "confidence": 0.8, "method": "spacy"}],
                    ...
                }
        """
        entities = {}

        # Strategy 1: Regex extraction (highest confidence)
        regex_entities = self._extract_with_regex(text)
        entities.update(regex_entities)

        # Strategy 2: spaCy NER (for product names, organizations, etc.)
        if self.nlp:
            spacy_entities = self._extract_with_spacy(text)
            # Merge spacy entities (don't override regex results)
            for key, value in spacy_entities.items():
                if key not in entities:
                    entities[key] = value

        return entities

    def _extract_with_regex(self, text: str) -> Dict[str, Any]:
        """
        Extract entities using regex patterns.

        Args:
            text: Input text

        Returns:
            dict: Extracted entities
        """
        entities = {}

        # Job ID
        job_id_match = re.search(self.PATTERNS["job_id"], text)
        if job_id_match:
            entities["job_id"] = {
                "value": job_id_match.group(0),
                "confidence": 1.0,
                "method": "regex"
            }

        # Quotation ID with line number
        quotation_line_match = re.search(self.PATTERNS["quotation_line"], text)
        if quotation_line_match:
            entities["quotation_id"] = {
                "value": quotation_line_match.group(1),
                "confidence": 1.0,
                "method": "regex"
            }
            entities["line_num"] = {
                "value": int(quotation_line_match.group(2)),
                "confidence": 1.0,
                "method": "regex"
            }
        else:
            # Try quotation ID without line number
            quotation_id_match = re.search(self.PATTERNS["quotation_id"], text)
            if quotation_id_match:
                entities["quotation_id"] = {
                    "value": quotation_id_match.group(0),
                    "confidence": 1.0,
                    "method": "regex"
                }

        # Price (convert to float)
        price_match = re.search(self.PATTERNS["price"], text)
        if price_match:
            price_str = price_match.group(1).replace(",", "")
            entities["price"] = {
                "value": float(price_str),
                "confidence": 0.95,
                "method": "regex"
            }

        # Quantity
        quantity_match = re.search(self.PATTERNS["quantity"], text)
        if quantity_match:
            entities["quantity"] = {
                "value": int(quantity_match.group(1)),
                "confidence": 0.9,
                "method": "regex"
            }

        # Email
        email_match = re.search(self.PATTERNS["email"], text)
        if email_match:
            entities["email"] = {
                "value": email_match.group(0),
                "confidence": 1.0,
                "method": "regex"
            }

        # Boat model
        boat_model_match = re.search(self.PATTERNS["boat_model"], text, re.IGNORECASE)
        if boat_model_match:
            entities["boat_model"] = {
                "value": boat_model_match.group(0).upper(),
                "confidence": 1.0,
                "method": "regex"
            }

        # Number selection (for disambiguation)
        number_match = re.match(self.PATTERNS["number_selection"], text.strip())
        if number_match:
            entities["number_selection"] = {
                "value": int(number_match.group(1)),
                "confidence": 1.0,
                "method": "regex"
            }

        return entities

    def _extract_with_spacy(self, text: str) -> Dict[str, Any]:
        """
        Extract entities using spaCy NER.

        Args:
            text: Input text

        Returns:
            dict: Extracted entities
        """
        entities = {}

        if not self.nlp:
            return entities

        doc = self.nlp(text)

        # Extract product names (from noun chunks)
        product_names = []
        for chunk in doc.noun_chunks:
            # Filter for likely product names (contains nouns, not too short)
            if len(chunk.text.split()) >= 2 and any(token.pos_ == "NOUN" for token in chunk):
                product_names.append({
                    "value": chunk.text,
                    "confidence": 0.7,
                    "method": "spacy"
                })

        if product_names:
            entities["product_names"] = product_names

        # Extract organizations (vendor names)
        orgs = [ent.text for ent in doc.ents if ent.label_ == "ORG"]
        if orgs:
            entities["vendor_names"] = [{
                "value": org,
                "confidence": 0.75,
                "method": "spacy"
            } for org in orgs]

        # Extract money entities (backup for regex)
        money = [ent.text for ent in doc.ents if ent.label_ == "MONEY"]
        if money and "price" not in entities:
            # Try to parse first money entity
            try:
                price_str = re.sub(r"[^\d.]", "", money[0])
                entities["price"] = {
                    "value": float(price_str),
                    "confidence": 0.6,
                    "method": "spacy"
                }
            except ValueError:
                pass

        return entities

    def extract_with_llm(self, text: str, target_entity: str, prompt_template: str) -> Optional[Any]:
        """
        Extract specific entity using LLM (fallback for complex cases).

        Args:
            text: Input text
            target_entity: Entity type to extract (e.g., "job_description", "item_name")
            prompt_template: Prompt template for extraction

        Returns:
            Extracted entity value or None
        """
        try:
            prompt = prompt_template.format(text=text, target_entity=target_entity)
            response = llm.invoke([{"role": "user", "content": prompt}])
            return response.content.strip()
        except Exception as e:
            print(f"[EntityExtractor] LLM extraction failed: {e}")
            return None

    def extract_job_id(self, text: str) -> Optional[str]:
        """Extract job ID (COST-XXXXXXXX format)."""
        entities = self.extract_all(text)
        return entities.get("job_id", {}).get("value")

    def extract_quotation_reference(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract quotation reference (ID and optional line number).

        Returns:
            dict: {"quotation_id": "AJMFQ-000001", "line_num": 1} or None
        """
        entities = self.extract_all(text)
        result = {}

        if "quotation_id" in entities:
            result["quotation_id"] = entities["quotation_id"]["value"]

        if "line_num" in entities:
            result["line_num"] = entities["line_num"]["value"]

        return result if result else None

    def extract_price(self, text: str) -> Optional[float]:
        """Extract price value."""
        entities = self.extract_all(text)
        return entities.get("price", {}).get("value")

    def extract_quantity(self, text: str) -> Optional[int]:
        """Extract quantity value."""
        entities = self.extract_all(text)
        return entities.get("quantity", {}).get("value")

    def extract_email(self, text: str) -> Optional[str]:
        """Extract email address."""
        entities = self.extract_all(text)
        return entities.get("email", {}).get("value")

    def extract_boat_model(self, text: str) -> Optional[str]:
        """Extract boat model."""
        entities = self.extract_all(text)
        return entities.get("boat_model", {}).get("value")

    def extract_number_selection(self, text: str) -> Optional[int]:
        """Extract number selection (for disambiguation)."""
        entities = self.extract_all(text)
        return entities.get("number_selection", {}).get("value")
