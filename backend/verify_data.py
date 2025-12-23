from database import SessionLocal, Product
from sqlalchemy import func

def verify():
    session = SessionLocal()
    try:
        count = session.query(func.count(Product.id)).scalar()
        print(f"Total Products: {count}")
        
        sample = session.query(Product).first()
        if sample:
            print(f"Sample Product: {sample.name}")
            print(f"Category: {sample.category}")
            print(f"Price: {sample.price}")
        else:
            print("No products found.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    verify()
