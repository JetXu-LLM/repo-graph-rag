import sys
import logging
from repo_knowledge_graph import RepoKnowledgeGraph
from llama_github import GithubRAG
import re

arangodb_pwd = 'arangodb_pwd'

# Example usage
def main():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    notebook_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    notebook_handler.setFormatter(formatter)

    logger.addHandler(notebook_handler)

    github_rag=GithubRAG(
        github_access_token="github_access_token", 
        openai_api_key="openai_api_key", 
        # mistral_api_key="mistral_api_key",
        huggingface_token="huggingface_token",
        # jina_api_key="jina_api_key"
        simple_mode=True
    )

    repo = github_rag.RepositoryPool.get_repository("JetXu-LLM/llama-github")
    repo_structure = repo.get_structure()

    # Initialize the knowledge graph
    kg = RepoKnowledgeGraph(
        repo=repo,
        host='http://localhost:8529',
        database=re.sub(r'[^a-zA-Z0-9_-]', '_', repo.full_name),
        username='root',
        password=arangodb_pwd
    )
    
    # Process the repository structure
    kg.build_knowledge_graph(repo.full_name, repo_structure)

if __name__ == "__main__":
    main()