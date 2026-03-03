"""Google Apps Skill – Gmail, Drive, Calendar."""

from backend.tools.google_gmail    import GoogleGmailTool
from backend.tools.google_drive    import GoogleDriveTool
from backend.tools.google_calendar import GoogleCalendarTool


def get_tools():
    return [
        GoogleGmailTool(),
        GoogleDriveTool(),
        GoogleCalendarTool(),
    ]
