from backend.tools.cron_tool import CronCreateTool, CronListTool, CronDeleteTool

def get_tools():
    return [CronCreateTool(), CronListTool(), CronDeleteTool()]
