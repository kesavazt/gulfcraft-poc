import random
import json
from sys import api_version
from sqlalchemy.orm import Session
from database import SessionLocal, Product,QuotationLines,EstimationLines, init_db, engine
import sqlalchemy
import openai
import os
import config


client = openai.AzureOpenAI(api_key=config.OPENAI_API_KEY,api_version=config.OPENAI_API_VERSION,azure_endpoint=config.AZURE_OPENAI_ENDPOINT)

# Categories and their specific items/vendors
CATEGORIES = {
    "Marine Engineering": {
        "items": ["Diesel Engine 500HP", "Propeller Shaft", "Hydraulic Steering Pump", "Fuel Filter", "Water Separator", "Exhaust Manifold", "Impeller Kit", "Transmission Gearbox", "Bow Thruster", "Stabilizer Fin"],
        "vendors": ["engineering@marine-supply.com", "parts@diesel-experts.com"]
    },
    "Hull & Deck": {
        "items": ["Marine Grade Plywood", "Fiberglass Resin", "Gelcoat White", "Teak Decking Plank", "Stainless Steel Cleat", "Anchor Chain", "Windlass", "Hatch Cover", "Portlight", "Antifouling Paint"],
        "vendors": ["sales@hull-deck.com", "materials@boat-builders.com"]
    },
    "Interior & Furniture": {
        "items": ["Leather Sofa", "Teak Table", "Cabin Mattress", "LED Ceiling Light", "Galley Stove", "Refrigerator 12V", "Marine Toilet", "Shower Mixer", "Curtain Fabric", "Carpet Roll"],
        "vendors": ["interiors@luxury-yachts.com", "decor@marine-living.com"]
    },
    "Electronics & Navigation": {
        "items": ["GPS Chartplotter", "Radar Dome", "VHF Radio", "Autopilot System", "Depth Sounder", "Fishfinder", "Satellite Phone", "Marine Battery", "Inverter 2000W", "Solar Panel"],
        "vendors": ["sales@marine-electronics.com", "tech@nav-systems.com"]
    },
    "Safety Equipment": {
        "items": ["Life Jacket", "Life Raft", "Flare Kit", "Fire Extinguisher", "First Aid Kit", "EPIRB", "Bilge Pump", "Searchlight", "Fog Horn", "Safety Harness"],
        "vendors": ["safety@sea-safe.com", "supplies@rescue-gear.com"]
    },
    "Deck Hardware": {
        "items": ["Winch", "Pulley Block", "Shackle", "Turnbuckle", "Rope 10mm", "Fender", "Boat Hook", "Ladder", "Bimini Top", "Canvas Cover"],
        "vendors": ["hardware@deck-pro.com", "rigging@sail-supply.com"]
    }
}

def generate_products(n=1000):
    products = []
    used_ids = set()
    
    for i in range(n):
        category = random.choice(list(CATEGORIES.keys()))
        base_item = random.choice(CATEGORIES[category]["items"])
        
        # Create variations
        item_name = f"{base_item} - Type {random.choice(['A', 'B', 'C'])} {random.randint(100, 999)}"
        description = f"High quality {base_item.lower()} for marine use. Specification {random.randint(1, 10)}."
        price = round(random.uniform(50, 10000), 2)
        
        # Ensure unique ID
        while True:
            d365_id = f"ITEM-{random.randint(10000, 99999)}"
            if d365_id not in used_ids:
                used_ids.add(d365_id)
                break
        
        # Mock embedding (all zeros for now as we don't want to call OpenAI 1000 times in this script)
        # In a real scenario, you'd batch generate these.
        embedding = [0.0] * 1536 
        
        products.append({
            "name": item_name,
            "description": description,
            "price": price,
            "d365_id": d365_id,
            "category": category,
            "embedding": embedding
        })
    return products

def update_vendor_emails():
    vendor_data = {}
    for cat, data in CATEGORIES.items():
        vendor_data[cat.lower()] = data["vendors"]
    
    with open("vendor_emails.json", "w") as f:
        json.dump(vendor_data, f, indent=2)
    print("Updated vendor_emails.json")

def batch_embed(texts, batch_size=100):
    all_embeddings = []
    #print(texts)
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch
        )

        all_embeddings.extend([x.embedding for x in response.data])
    return all_embeddings

def main():
    print("Initializing Database...")
    init_db()
    
    session = SessionLocal()

    try:
        
        # Clear existing ProjQuotationLines and ingest data again
        print("Inserting Quotation Lines")
        session.query(QuotationLines).delete()
        session.commit()
        quotations = json.load(open("ProjQuotationLines.json","r",encoding="utf-8"))
        quotations = quotations["value"]
        descriptions = []
        for q in quotations:
            text = q["AFZName"].strip().replace("\n","")
            if len(text) != 0:
                descriptions.append(text)
            else:
                descriptions.append("empty")
        
        print("Generating embeddings")
        description_embeddings = batch_embed(descriptions)
        print("Generated embeddings")
        i = 0
        for q in quotations:
            obj = QuotationLines(
                quotation_id = q["QuotationId"],
                description = q["AFZName"],
                sales_price = q["SalesPrice"],
                line_num = q["LineNum"],
                afz_boat_model_id = q["AFZBoatModelId"],
                embedding = description_embeddings[i]
            )
            session.add(obj)
            i += 1
        session.commit()

        # Clear existing EstimationLines and ingest data again
        print("Inserting EstimationLines")
        session.query(EstimationLines).delete()
        estimations = json.load(open("EstimationLines.json","r",encoding="utf-8"))
        estimations = estimations["value"]
        for e in estimations:
            obj = EstimationLines(
                quotation_id = e["QuotationId"],
                line_num = e["LineNum"],
                item_type = e["ItemType"],
                item_name = e["ItemName"],
                std_item_code = e["StdItemCode"],
                uom = e["UOM"],
                item_qty = e["ItemQty"],
                average_price = e["AveragePrice"],
                last_purchase_price = e["LastPurchPrice"],
                sales_price = e["SalesPrice"]
            )
            session.add(obj)
        session.commit()
        
        # Clear Existing Inventory and ingest data again
        print("Inserting Inventory")
        session.query(Product).delete()
        inventory = json.load(open("Products.json","r"))
        inventory = inventory["value"]
        for i in inventory:
            if len(i["ReleasedProducts"]) == 0:
                print("here")
                print(i)
            else:
                obj = Product(
                    item_number = i["ProductNumber"],
                    unit_cost = (i["ReleasedProducts"][0]["UnitCost"] ),#,i["ReleasedProducts"][1]["UnitCost"]),
                    vendor_email = "vinod.ihava@gulfcraftinc.com"
                )
                session.add(obj)

        #with engine.connect() as conn:
        #    conn.execute(sqlalchemy.text(" delete from quotation_lines where quotation_id not in (select quotation_id from estimation_lines);"))
        #    conn.execute(sqlalchemy.text("ALTER TABLE quotation_lines ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', description)) STORED;"))
        session.commit()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")
        session.rollback()
    finally:
        session.close()

    update_vendor_emails()

if __name__ == "__main__":
    main()
