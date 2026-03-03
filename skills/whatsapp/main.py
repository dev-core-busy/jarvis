from backend.tools.whatsapp import WhatsAppSendTool, WhatsAppStatusTool

def get_tools():
    return [WhatsAppSendTool(), WhatsAppStatusTool()]
