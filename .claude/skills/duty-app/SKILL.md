\---

name: duty-app

description: Use this skill when designing, implementing, reviewing, or modifying the company duty scheduling web app. The app uses Streamlit, Supabase, spreadsheet-style registration screens, simple employee-number login, and mobile-friendly personal schedule lookup.

\---



\# Duty App Skill



\## Project Purpose



This project is a company duty scheduling web app.



The goal is to build:

\- Admin web screens for registering, editing, and viewing duty schedules

\- Mobile-friendly personal schedule lookup for employees

\- Simple login by employee number only

\- Persistent login if possible

\- Supabase-based data storage

\- Streamlit-based MVP

\- Spreadsheet-style registration screens that support manual key-in and Excel copy/paste



\## Core Product Definition



This is not an automatic shift-generation system.



Do not focus on automatic scheduling rules unless the user explicitly asks.



The main workflow is:



1\. Register master data

2\. Paste or key in duty schedule data like Excel

3\. Validate data

4\. Save data to Supabase

5\. Allow admin users to view and edit schedules

6\. Allow normal users to view their own schedule on mobile



\## Important Screens



Create and maintain these screens:



1\. Login screen

&#x20;  - Employee number input only

&#x20;  - No password for MVP

&#x20;  - Store login state if possible



2\. User registration screen

&#x20;  - Spreadsheet-style editor

&#x20;  - Add row

&#x20;  - Delete row

&#x20;  - Excel copy/paste

&#x20;  - Query

&#x20;  - Save



3\. Department registration screen

&#x20;  - Spreadsheet-style editor

&#x20;  - Add row

&#x20;  - Delete row

&#x20;  - Excel copy/paste

&#x20;  - Query

&#x20;  - Save



4\. Team registration screen

&#x20;  - Spreadsheet-style editor

&#x20;  - Add row

&#x20;  - Delete row

&#x20;  - Excel copy/paste

&#x20;  - Query

&#x20;  - Save



5\. Work type registration screen

&#x20;  - Spreadsheet-style editor

&#x20;  - Work types such as 주, 야, OFF, 연차, 특근

&#x20;  - Add row

&#x20;  - Delete row

&#x20;  - Excel copy/paste

&#x20;  - Query

&#x20;  - Save



6\. Duty schedule registration screen

&#x20;  - Spreadsheet-style editor

&#x20;  - Excel duty schedule copy/paste

&#x20;  - Preview before save

&#x20;  - Validate users, departments, teams, and work types

&#x20;  - Save to Supabase



7\. Full schedule inquiry screen

&#x20;  - Filter by month, department, team, employee, work type

&#x20;  - Display in Excel-like monthly grid

&#x20;  - Allow admin or manager edit if permitted



8\. Personal mobile schedule screen

&#x20;  - Mobile-friendly layout

&#x20;  - Show today’s duty

&#x20;  - Show monthly schedule

&#x20;  - Show work types with clear colors



\## Common Registration Screen Rules



All registration screens must follow the same pattern:



\- Top title and short description

\- Search/filter area at the top

\- Spreadsheet-style editable grid

\- Buttons in consistent order

\- Query / Add row / Delete row / Save

\- Support manual key-in

\- Support Excel copy/paste

\- Support dynamic rows or enough empty rows for pasted data

\- Validate before save

\- Show clear success/error messages



\## Data Integrity Rules



Use master data to keep data consistent.



Required master tables:

\- users

\- departments

\- teams

\- work\_types



Required transaction tables:

\- work\_schedules

\- schedule\_import\_batches

\- schedule\_change\_logs



Important constraints:

\- One employee can have only one duty record per date

\- Work type must exist in work\_types

\- Department must exist in departments

\- Team must exist in teams

\- User must exist in users

\- Do not physically delete important records if soft delete or is\_active can be used

\- Keep created\_at, updated\_at, created\_by, updated\_by where practical

\- Keep schedule change logs for duty schedule edits



\## Permission Model



Use a simple role model:



\- USER: can view only their own schedule

\- MANAGER: can view and edit schedules for their department or team

\- ADMIN: can manage all master data and all schedules



For MVP, employee-number-only login is acceptable.



But always mention this limitation when reviewing:

\- Anyone who knows another employee number could log in as that employee.

\- Later improvement can be employee number + name, employee number + PIN, or real authentication.



\## Technology Rules



Use:

\- Python

\- Streamlit

\- Supabase

\- pandas



Do not use MCP unless the user explicitly asks.



Supabase connection info should be read from:

\- `.streamlit/secrets.toml`, or

\- `.env`



The app should still run with sample data or local fallback when Supabase settings are missing, especially during early MVP development.



\## Design Rules



Always follow DESIGN.md if it exists.



The UI should look like a clean internal business web app, not a rough test page.



Design priorities:

\- Wide layout

\- Clean white or light gray background

\- Card-style filter areas

\- Consistent button placement

\- Clear table layout

\- Work type colors

\- Mobile-friendly personal schedule screen

\- Avoid excessive decoration

\- Avoid a basic Streamlit-only look



\## Development Behavior



Before creating or changing many files:

1\. Read CLAUDE.md if it exists

2\. Read DESIGN.md if it exists

3\. Check the current folder structure

4\. Explain the planned changes briefly

5\. Then implement



When fixing errors:

1\. Preserve existing working features

2\. Explain the cause simply

3\. Make the smallest safe fix

4\. Re-run or explain how to test



When creating the first MVP:

1\. Create the project structure

2\. Create CLAUDE.md

3\. Create DESIGN.md

4\. Create docs files

5\. Create Streamlit app structure

6\. Implement screens incrementally

7\. Confirm the app runs locally

