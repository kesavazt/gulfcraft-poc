from core.database import engine
from sqlalchemy import text

def migrate():
    with engine.connect() as conn:
        print("Checking for item_type column...")
        try:
            conn.execute(text("ALTER TABLE costing_line_items ADD COLUMN item_type VARCHAR;"))
            conn.commit()
            print("Successfully added item_type column.")
        except Exception as e:
            if "already exists" in str(e).lower():
                print("Column item_type already exists.")
            else:
                print(f"Error: {e}")

if __name__ == "__main__":
    migrate()
