# UrbanNest Realty CRM - User Manual

This guide covers the day-to-day workflows in the UrbanNest team workspace.
Your available pages and actions depend on your role and permissions.

> **Screenshot placeholder - Sign in:** Add the sign-in screen image here.

## 1. Sign in and account setup

1. Open the UrbanNest workspace URL provided by your team.
2. Sign in with your work email and password.
3. If you received a temporary password, create a new password before using
   the CRM. Use at least 12 characters.
4. To recover access, ask your team owner, manager, or permitted co-owner to
   issue a password reset. The app does not provide email-based self-service
   password resets.
5. Use **Sign out** when you finish on a shared device. Your access token is
   kept for the current browser tab and removed when you sign out.

> **Screenshot placeholder - First sign-in:** Add the required password change
> screen image here.

## 2. Know your role

| Role | Typical access |
|---|---|
| Owner | All team CRM records and team-account administration. |
| Manager | Team leads and follow-ups, plus agent-account administration. |
| Co-owner | Access determined by the owner-set read, write, delete, and user-management permissions. |
| Agent | Leads assigned to you and their related follow-ups. |

The backend enforces access on every request. If an action is missing or
unavailable, ask your workspace administrator to check your role and
permissions.

## 3. Dashboard

The **Overview** page summarizes your visible leads, pipeline stages, and
follow-ups due today or overdue. Select a lead or task to open its details.
Use **Refresh** to request the latest workspace data.

> **Screenshot placeholder - Overview dashboard:** Add the dashboard image here.

## 4. Work with leads

### Find and review a lead

1. Open **Leads**.
2. Search by a lead name, contact detail, or location. Use the controls in
   the table headers to filter by location, bedrooms, source, or stage; select
   a column heading to sort. These header filters apply to the currently
   loaded lead list.
3. On the leads page, press `/` to focus the search field and `Escape` to
   dismiss an open panel or dialog.
4. Select a lead to review contact details, property preferences, notes, and
   its activity history.

### Add or update a lead

1. Select **Add lead** if your role has write access.
2. Enter the details you have. Email, phone, budget, bedrooms, location, and
   notes are optional; the lead name is required.
3. Names are trimmed and formatted in Title Case; emails are trimmed and
   lowercased. Phone numbers use a country selector and are checked against
   that country's numbering rules before saving.
4. Search for a location and select one of the verified suggestions. An
   unselected typed location is not saved. Suggestions use Photon with
   OpenStreetMap data; attribution appears below the field.
5. If another lead already has the same normalized name, the app asks whether
   you want to create a separate record. Use only accurate, necessary
   information and follow your organization's privacy practices.
6. Open a lead to update its pipeline stage, log a call or other interaction,
   or add a follow-up.

Owners and co-owners can assign a lead to any active team member. Managers can
assign leads only to agents who report directly to them; agents are assigned
their own new leads by default. A manager-created lead is assigned to that
manager unless an eligible agent is selected. Owners can link agents to a
manager from **Team** using the **Reports to** control; existing agents without
a manager link are not available to managers for assignment until linked.

### Import a CSV or Excel spreadsheet

Managers, owners, and writable co-owners can import a UTF-8 CSV or Excel `.xlsx`
file from the Leads page. Excel imports use the first worksheet. The first row
must use the API's column names:

- Required: `full_name`
- Optional: `email`, `phone`, `source`, `status`, `budget_min_inr`,
  `budget_max_inr`, `bhk`, `preferred_location`, `notes`, `assigned_to`

Names and emails are normalized on import. Phone values must be valid; provide
an international number with its country prefix, or a national number for the
configured default region. Locations imported as text remain legacy free-text
values; use the lead form's location suggestions to save structured,
geocoded location data.

Header names are case-insensitive, but every column must be supported and
unique. Use whole numbers for budgets in INR and for `bhk`. Files may be at most
2 MiB and 500 data rows. The browser checks the spreadsheet structure before
upload; the API repeats validation and reports row-specific errors. Correct
rejected records before importing them again.

> **Screenshot placeholder - Leads and lead details:** Add the leads list and
> lead detail images here.

## 5. Follow-ups and activity

- Add a follow-up from a lead's detail panel. Set a clear title and due date;
  include a short description when it helps the assignee.
- Open **Follow-ups** to review work, filter by due status, and mark completed
  tasks done. Select a related lead to return to its record.
- Open **Activity** or the notification control to review recent team changes.
  Select an event to open the related record when available.

> **Screenshot placeholder - Follow-ups and activity:** Add these page images
> here.

## 6. Team accounts

Owners, managers, and co-owners with user-management permission can access
**Team**. Managers and co-owners can manage agent accounts; owners can manage
the broader set of team roles and permissions.

When creating an account or resetting a password, the app may show a temporary
password once. An owner can use **Reset password** on an individual member's
row to reset that account without resetting the rest of the team. Managers and
user-enabled co-owners can reset agent accounts according to their permissions.
Share the temporary password privately; the user must change it at first
sign-in. The owner can also reset all team passwords and download a CSV; that
file contains live temporary credentials, so store and distribute it securely
and delete it when no longer needed.

> **Screenshot placeholder - Team access:** Add the team management image here.

### Explore the organization chart

Every signed-in team member can open **Org chart** from the sidebar to explore
active team roles and reporting lines. Search by a person's name or role, select
a card to view its reporting details, and expand or collapse branches as needed.
Contact details are not shown on this page.

> **Screenshot placeholder - Org chart explorer:** Add the org chart image here.

## 7. Profile, theme, and navigation

- Open your profile from the account area to update supported profile details
  or change your password.
- Use the theme control to switch between light and dark display.
- Use the sidebar control to collapse or expand navigation.
- Use **Privacy policy** or **Cookie and storage choices** in the workspace
  footer to review the service's data handling and update your browser-storage
  choice.
- Use **UrbanNest Realty website** in the footer to open the company website in
  a new tab.
- Refreshing the browser restores the current workspace section for the current
  tab. Signing out clears that section so the next sign-in starts at Overview.

> **Screenshot placeholder - Profile and privacy choices:** Add these images
> here.

## 8. Privacy and safe data handling

UrbanNest uses a first-party cookie to remember your storage choice. If you
allow optional preferences, first-party cookies also remember the theme and
collapsed-sidebar setting. The sign-in token and current workspace section use
tab-scoped session storage. The app does not use advertising cookies or
trackers. Choosing **Essential only** removes persistent display preferences;
the theme and sidebar controls still work until the tab is closed.

The privacy page is a draft until the service operator fills in the legal
entity, privacy contact, deployment providers and locations, retention details,
and any applicable jurisdiction-specific information. Use fictional data in
demos and contact your workspace operator for data requests.

## 9. Troubleshooting

- **Sign-in fails:** Check your email and password. Ask an administrator for a
  reset if needed.
- **The workspace is unavailable:** Check your connection and contact the
  workspace administrator if the API remains disconnected.
- **A page or action is missing:** Your account may not have the required
  role or permission.
- **A CSV row is rejected:** Check the row number and message in the import
  results, correct the row, and retry.
- **A temporary password is lost:** Ask an authorized administrator to issue
  another reset; existing passwords cannot be retrieved.
