from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.title = "Costing Sheet"

# Add headers
headers = ["Job ID", "Item Details", "Price", "Status", "Date"]
ws.append(headers)

# Add some dummy data
ws.append(["JOB-001", "Marine Plywood", 150.00, "Completed", "2023-10-27"])

wb.save("templates/costing_template.xlsx")
print("Template created.")
