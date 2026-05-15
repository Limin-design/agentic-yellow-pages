import os  
import json  
import hashlib  
from dotenv import load_dotenv  
  
from azure.core.credentials import AzureKeyCredential  
from azure.search.documents import SearchClient  
from azure.search.documents.indexes import SearchIndexClient  
from azure.search.documents.indexes.models import (  
    SearchIndex,  
    SimpleField,  
    SearchableField,  
    SearchFieldDataType  
)  
  
load_dotenv()  
  
# Required env vars  
AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")  
AZURE_SEARCH_ADMIN_KEY = os.getenv("AZURE_SEARCH_ADMIN_KEY")  
AZURE_SEARCH_INDEX_NAME = os.getenv("AZURE_SEARCH_INDEX_NAME", "idx-docs-rag-prod")  
  
if not AZURE_SEARCH_ENDPOINT or not AZURE_SEARCH_ADMIN_KEY:  
    raise RuntimeError("Missing AZURE_SEARCH_ENDPOINT or AZURE_SEARCH_ADMIN_KEY")  
  
credential = AzureKeyCredential(AZURE_SEARCH_ADMIN_KEY)  
  
  
def ensure_index(index_name: str):  
    """Create index if it doesn't exist."""  
    index_client = SearchIndexClient(  
        endpoint=AZURE_SEARCH_ENDPOINT,  
        credential=credential  
    )  
  
    existing = [idx.name for idx in index_client.list_indexes()]  
    if index_name in existing:  
        print(f"[OK] Index already exists: {index_name}")  
        return  
  
    index = SearchIndex(  
        name=index_name,  
        fields=[  
            SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),  
            SimpleField(name="url", type=SearchFieldDataType.String, filterable=True),  
            SimpleField(name="domain", type=SearchFieldDataType.String, filterable=True, facetable=True),  
            SearchableField(name="title", type=SearchFieldDataType.String),  
            SearchableField(name="content", type=SearchFieldDataType.String),  
        ]  
    )  
  
    index_client.create_index(index)  
    print(f"[OK] Created index: {index_name}")  
  
  
def make_id(url: str) -> str:  
    return hashlib.sha1(url.encode("utf-8")).hexdigest()  
  
  
def load_jsonl(path: str):  
    docs = []  
    with open(path, "r", encoding="utf-8") as f:  
        for line in f:  
            if not line.strip():  
                continue  
            row = json.loads(line)  
  
            url = row.get("url", "").strip()  
            if not url:  
                continue  
  
            doc = {  
                "id": make_id(url),  
                "url": url,  
                "domain": row.get("domain", ""),  
                "title": row.get("title", ""),  
                "content": row.get("text", ""),  # from scraper.py output  
            }  
            docs.append(doc)  
    return docs  
  
  
def upload_in_batches(search_client: SearchClient, docs, batch_size=500):  
    total = len(docs)  
    uploaded = 0  
  
    for i in range(0, total, batch_size):  
        batch = docs[i:i + batch_size]  
        result = search_client.upload_documents(documents=batch)  
        ok = sum(1 for r in result if r.succeeded)  
        uploaded += ok  
        print(f"[BATCH] {i}-{i+len(batch)-1} => {ok}/{len(batch)} succeeded")  
  
    print(f"\n[DONE] Uploaded {uploaded}/{total} docs")  
  
  
def main():  
    input_file = os.getenv("SCRAPER_OUTPUT_FILE", "scraped.jsonl")  
  
    ensure_index(AZURE_SEARCH_INDEX_NAME)  
  
    search_client = SearchClient(  
        endpoint=AZURE_SEARCH_ENDPOINT,  
        index_name=AZURE_SEARCH_INDEX_NAME,  
        credential=credential  
    )  
  
    docs = load_jsonl(input_file)  
    if not docs:  
        print("No docs found to upload.")  
        return  
  
    upload_in_batches(search_client, docs)  
  
  
if __name__ == "__main__":  
    main()  
