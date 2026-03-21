from backend.tools.whatsapp import WhatsAppSendTool, WhatsAppContactsTool, WhatsAppStatusTool

def get_tools():
    return [WhatsAppSendTool(), WhatsAppContactsTool(), WhatsAppStatusTool()]
