from backend.tools.knowledge import KnowledgeTool, KnowledgeManageTool


def get_tools():
    return [KnowledgeTool(), KnowledgeManageTool()]
