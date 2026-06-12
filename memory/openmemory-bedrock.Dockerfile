# The upstream OpenMemory image does not ship boto3, which mem0's
# aws_bedrock provider needs (verified live 2026-06-12: "The 'boto3' library
# is required"). This derived image adds it — nothing else changes.
FROM mem0/openmemory-mcp:latest
RUN pip install --no-cache-dir boto3
