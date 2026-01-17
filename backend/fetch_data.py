import json
import requests

url =  "https://gcdev06a48d842c8e439bc1devaos.cloudax.uae.dynamics.com/data/ProjQuotationLines"
token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6IlBjWDk4R1g0MjBUMVg2c0JEa3poUW1xZ3dNVSIsImtpZCI6IlBjWDk4R1g0MjBUMVg2c0JEa3poUW1xZ3dNVSJ9.eyJhdWQiOiJodHRwczovL2djZGV2MDZhNDhkODQyYzhlNDM5YmMxZGV2YW9zLmNsb3VkYXgudWFlLmR5bmFtaWNzLmNvbSIsImlzcyI6Imh0dHBzOi8vc3RzLndpbmRvd3MubmV0LzM1YTY4M2U2LTVkN2UtNDFjNi1iNDI4LWYwYjdhNWJkZGQwZC8iLCJpYXQiOjE3Njg1NDk3OTksIm5iZiI6MTc2ODU0OTc5OSwiZXhwIjoxNzY4NTUzNjk5LCJhaW8iOiJrMlpnWUZncUhQMXhqdDlrMzlUWnZqdllGNnlhRGdBPSIsImFwcGlkIjoiOWRiOGU5ZDktYzkzMC00YWFhLTg2YWMtMGEwMWMwMjJhMmJkIiwiYXBwaWRhY3IiOiIxIiwiaWRwIjoiaHR0cHM6Ly9zdHMud2luZG93cy5uZXQvMzVhNjgzZTYtNWQ3ZS00MWM2LWI0MjgtZjBiN2E1YmRkZDBkLyIsImlkdHlwIjoiYXBwIiwib2lkIjoiZTM2YTVlMjUtODA0Ni00YjgxLWE4NmYtYzI4ZDNkYzQxZGFjIiwicmgiOiIxLkFYTUE1b09tTlg1ZHhrRzBLUEMzcGIzZERSVUFBQUFBQUFBQXdBQUFBQUFBQUFCekFBQnpBQS4iLCJzdWIiOiJlMzZhNWUyNS04MDQ2LTRiODEtYTg2Zi1jMjhkM2RjNDFkYWMiLCJ0aWQiOiIzNWE2ODNlNi01ZDdlLTQxYzYtYjQyOC1mMGI3YTViZGRkMGQiLCJ1dGkiOiJmNXd2RjBnakdrUzhMYTZJYmJwS0FBIiwidmVyIjoiMS4wIiwieG1zX2FjdF9mY3QiOiIzIDkiLCJ4bXNfZnRkIjoiZXk3RXBfZHlLWmxmVmdISmpldFpnSkpRY1JOU1NEVFU2dE5OQlA1Ty1GTUJaWFZ5YjNCbGQyVnpkQzFrYzIxeiIsInhtc19pZHJlbCI6IjEyIDciLCJ4bXNfcmQiOiIwLjQyTGxZQkppTEJZUzRXQVhFdkFvMVRwMkxGM2FwVGRFTXpWYm85MFFLTW9wSkJEZjJwUFY2bEhrUE12Q25sdjFYSjBKVUpSRFNFQ1VBUUlPUUdrQSIsInhtc19zdWJfZmN0IjoiOSAzIn0.EK40Qv0iIPYWGbXfkem5BvD-CQuwvXGQhmN8zWzZ6TjB-L1e3Papfg9uH3SUbkTtS2Nw-h3YIikublColjVUmygF0Q6D5A6NwxXOWZ_TOgdYPWqqkumBS4KbaTDML9jvRmxoPcFQYkhoMeug-BGb8IaYXu5g_j0ru4R5ko62wx9PnxbvXNGNgTrpdFqS8dbArP9DSXNEDnnQ3VRXMG2itl6Ll-uEC_TD3yE5NLpMJQRTt-eErqBStazxNTIncGWVpcCgIMff5RUGxxksMegRM0R-wy7Qa0BVLOTVr8f0k7Il4Qje0r2HvNx9gluI5PzvC97Y7q1W1VVM7TdUX61bjg"
headers = {
    "Authorization": f"Bearer {token}"
}
quotations = []
estimations = []
products = []

# ProjQuotationLines
'''while url:
    response = requests.get(url,headers=headers)
    print(response)
    print(response.headers["Content-type"])
    if response.status_code == 200 :
        tmp = response.json()
        quotations += tmp["value"]
        if "@odata.nextLink" in tmp:
            url = tmp["@odata.nextLink"]
        else:
            url = None
    else:
        url = None
        print("Error fetching response")
        exit()

fout = open("ProjQuotationLines.json","w")
json.dump({"value": quotations},fp=fout)
'''
# EstimationLines
url = "https://gcdev06a48d842c8e439bc1devaos.cloudax.uae.dynamics.com/data/GC_SeaThroughCosting_Entity"
while url:
    response = requests.get(url,headers=headers)
    print(response)
    print(response.headers["Content-type"])
    if response.status_code == 200 :
        tmp = response.json()
        estimations += tmp["value"]
        if "@odata.nextLink" in tmp:
            url = tmp["@odata.nextLink"]
        else:
            url = None
    else:
        url = None
        print("Error fetching response")
        exit()

fout = open("EstimationLines.json","w")
json.dump({"value": estimations},fp=fout)


# Products
url = "https://gcdev06a48d842c8e439bc1devaos.cloudax.uae.dynamics.com/data/ProductsV2?cross-company=true&%24expand=ReleasedProducts(%24select=UnitCost,ItemNumber)&%24select=ProductNumber"
while url:
    response = requests.get(url,headers=headers)
    print(response)
    print(response.headers["Content-type"])
    if response.status_code == 200 :
        tmp = response.json()
        products += tmp["value"]
        if "@odata.nextLink" in tmp:
            url = tmp["@odata.nextLink"]
        else:
            url = None
    else:
        url = None
        print("Error fetching response")
        exit()

fout = open("Products.json","w")
json.dump({"value": products},fp=fout)