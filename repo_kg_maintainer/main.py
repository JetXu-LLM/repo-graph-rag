import sys
import logging
from repo_knowledge_graph import RepoKnowledgeGraph
from llama_github import GithubRAG
import re
from dotenv import load_dotenv
import os

load_dotenv('/Users/xujiantong/Code/repos/repo-graph-rag/.env')

# Example usage
def main():
    # Set up logging
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    notebook_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    notebook_handler.setFormatter(formatter)

    logger.addHandler(notebook_handler)

    # Get environment variables
    github_token = os.environ.get('GITHUB_ACCESS_TOKEN')
    mistral_key = os.environ.get('MISTRAL_API_KEY')
    huggingface_token = os.environ.get('HUGGINGFACE_TOKEN')
    # mistral_key = os.environ.get('MISTRAL_API_KEY')
    # jina_key = os.environ.get('JINA_API_KEY')
    
    # Database configuration
    arangodb_host = os.environ.get('ARANGODB_HOST', 'http://localhost:8529')
    arangodb_username = os.environ.get('ARANGODB_USERNAME', 'root')
    arangodb_pwd = os.environ.get('ARANGODB_PASSWORD')

    # Initialize GitHub RAG
    github_rag = GithubRAG(
        github_access_token=github_token,
        # openai_api_key=openai_key,
        mistral_api_key=mistral_key,
        huggingface_token=huggingface_token,
        # jina_api_key=jina_key,
        simple_mode=True
    )

    # Get repository and structure
    repo = github_rag.RepositoryPool.get_repository("apache/airflow")
    repo_structure = repo.get_structure()

    # Initialize the knowledge graph
    kg = RepoKnowledgeGraph(
        repo=repo,
        host=arangodb_host,
        database=re.sub(r'[^a-zA-Z0-9_-]', '_', repo.full_name),
        username=arangodb_username,
        password=arangodb_pwd
    )
    
    # # Process the repository structure
    kg.build_knowledge_graph(repo.full_name, repo_structure)

if __name__ == "__main__":
    main()
