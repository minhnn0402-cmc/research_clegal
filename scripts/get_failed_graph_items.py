import os
import json
import argparse
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv
from bson import json_util

# Load environment variables
load_dotenv()

def get_mongo_client(host=None, port=None, user=None, password=None):
    """
    Creates a MongoDB client using environment variables or provided arguments.
    """
    host = host or os.getenv("MONGO_PROD_HOST", "localhost")
    port = int(port or os.getenv("MONGO_PROD_PORT", 27017))
    user = user or os.getenv("MONGO_PROD_USER")
    password = password or os.getenv("MONGO_PROD_PASSWORD")

    if user and password:
        uri = f"mongodb://{user}:{password}@{host}:{port}"
    else:
        uri = f"mongodb://{host}:{port}"
    
    return MongoClient(uri)

def retrieve_failed_items(client, db_name, coll_name, output_file):
    """
    Queries MongoDB for failed items in cls_graph and saves them to a JSON file.
    """
    db = client[db_name]
    collection = db[coll_name]

    print(f"Querying collection: {db_name}.{coll_name}")
    
    # Filter for documents where graph extraction has failed
    query = {"cls_graph.has_failed": True}
    
    # Projection for efficiency
    projection = {
        "cls_ID": 1,
        "cls_type": 1,
        "cls_graph.failed": 1,
        "cls_graph.updated_at": 1
    }

    cursor = collection.find(query, projection)
    
    failed_items = []
    stats = {
        "total_documents_analyzed": 0,
        "total_failed_mentions": 0,
        "failure_types": {},
        "generated_at": datetime.now().isoformat()
    }

    print("Processing results...")
    for doc in cursor:
        stats["total_documents_analyzed"] += 1
        doc_id = doc.get("cls_ID")
        doc_type = doc.get("cls_type")
        graph_failed = doc.get("cls_graph", {}).get("failed", [])

        for entry in graph_failed:
            source_key = entry.get("source_key")
            source_type = entry.get("source_type")
            mentions = entry.get("failed", [])

            for mention in mentions:
                stats["total_failed_mentions"] += 1
                
                # Identify failure type (e.g., luat, nghidinh)
                mention_type = "unknown"
                for key in mention.keys():
                    if key not in ["information", "position_start", "position_end", "index", "check_in_quotes"]:
                        mention_type = key
                        break
                
                stats["failure_types"][mention_type] = stats["failure_types"].get(mention_type, 0) + 1

                failed_items.append({
                    "doc_id": doc_id,
                    "doc_type": doc_type,
                    "source_key": source_key,
                    "source_type": source_type,
                    "mention_type": mention_type,
                    "mention_content": mention.get(mention_type, {}).get("information") if mention_type != "unknown" else mention.get("information"),
                    "full_mention_data": mention,
                    "reason": "Resolution failure: Mention identified but target document ID could not be found."
                })

    # Prepare final output
    output_data = {
        "summary": stats,
        "failed_items": failed_items
    }

    print(f"Found {stats['total_failed_mentions']} failed mentions across {stats['total_documents_analyzed']} documents.")
    
    # Save to file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4, default=json_util.default, ensure_ascii=False)
    
    print(f"Data saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export failed graph extraction items from MongoDB.")
    parser.add_argument("--output", default="failed_graph_items.json", help="Path to output JSON file.")
    parser.add_argument("--db", help="Database name (overrides .env IE_DATABASE).")
    parser.add_argument("--coll", help="Collection name (overrides .env IE_COLLECTION).")
    
    args = parser.parse_args()

    # Use args if provided, otherwise fallback to .env
    db_name = args.db or os.getenv("IE_DATABASE", "ie")
    coll_name = args.coll or os.getenv("IE_COLLECTION", "ie_collection")

    try:
        client = get_mongo_client()
        retrieve_failed_items(client, db_name, coll_name, args.output)
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'client' in locals():
            client.close()
