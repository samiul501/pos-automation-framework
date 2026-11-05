# Employee Creation — Test Cases

Module: Employee (Configuration → Entity Master Data → Employee → Employee Create)

> **Knowledge gap:** `knowledge/posapp/` has no `modules/employee.md`, `business-rules/employee-rules.md`, or workflow doc yet (only Purchase is documented). Field-level facts below (labels, required fields, cascading dropdowns, save behavior) come from direct inspection of the live Employee Create screen, not from documented business rules. Anything not directly observed is marked `Assumption:` and should be confirmed with business/dev before being treated as a defect if it fails.
>
> **Terminology note:** Supervisor and Line Manager are required fields in the main Personal Info section. Business Unit, Office, and Warehouse are only reachable after checking **User** (they belong to the User Account → User Permission sub-section, used to grant the employee a system login). The requirement groups all five as "assign," so TC-EMP-001 covers all five in one flow.

---

### TC-EMP-001: Create employee with all required fields plus Business Unit, Office, Warehouse, Supervisor and Line Manager assigned
Priority: Critical
Preconditions:
  - Logged in as a user authorized to create employees (Configuration → Entity Master Data → Employee is visible).
  - At least one Business Unit, Office, and Warehouse exist in master data.
  - At least one existing employee (e.g. a supervisor candidate) exists to search for in Supervisor/Line Manager.
Test Steps:
  1. Navigate to Configuration → Entity Master Data → Employee.
  2. Click **Employee Create**.
  3. Fill all required Personal Info fields: Name, Designation, Mobile No, Employee Type, Office, NID/Citizen/Civil/NIN/IDNumber.
  4. Search and select Supervisor.
  5. Search and select Line Manager.
  6. Check **User**.
  7. Enter Password and Confirm Password (matching).
  8. Select Business Unit.
  9. Select Office (User Permission section — populates after Business Unit is chosen).
  10. Select Warehouse (populates after Office is chosen).
  11. Click **Add**.
  12. Verify the row appears in the User Permission table with the selected Business Unit/Office/Warehouse.
  13. Click **Save**.
Test Data:
  - Name: `Habib_1234` | Designation: `QA` | Mobile No: `01700000003` | Employee Type: `Full Time` | Office: `StoreB Head Office` | NID: 16-digit unique number
  - Supervisor / Line Manager: existing employee, e.g. `Jane Manager`
  - Password / Confirm Password: `123456`
  - Business Unit: `POS App` | Office (User Permission): `StoreB Head Office` | Warehouse: `StoreB Warehouse One`
Expected Result:
  - User Permission row is added without error before Save.
  - On Save, a success notification ("Created Successfully") is shown and the employee appears in the Employee list with the entered details.

---

### TC-EMP-002: Create employee with only mandatory fields (no optional personal details, no User account)
Priority: High
Preconditions: Same access as TC-EMP-001.
Test Steps:
  1. Navigate to Employee Create.
  2. Fill only the required fields: Name, Designation, Mobile No, Employee Type, Office, NID, Supervisor, Line Manager.
  3. Leave all optional fields (Email, HR Position, Department, Gender, addresses, etc.) empty.
  4. Leave **User** unchecked.
  5. Click **Save**.
Test Data: Same required-field values as TC-EMP-001, without a User account.
Expected Result: Employee is created successfully without a linked system user; success notification shown.

---

### TC-EMP-003: Required field validation (data-driven)
Priority: High
Preconditions: Same access as TC-EMP-001.
Test Steps:
  1. Navigate to Employee Create.
  2. Fill all required fields with valid data.
  3. Clear exactly one required field (per data row below).
  4. Click **Save**.
  5. Repeat for each field.
Test Data (one field left empty per run): Name; Designation; Mobile No; Employee Type; Office; NID/Citizen/Civil/NIN/IDNumber; Supervisor; Line Manager.
Expected Result: Save is blocked; a validation message is shown against the empty field; no employee is created.

---

### TC-EMP-004: Mobile No boundary/format validation
Priority: Medium
Preconditions: Same access as TC-EMP-001.
Test Steps:
  1. Navigate to Employee Create, fill all other required fields validly.
  2. Enter an invalid Mobile No (e.g. 9 digits, or non-numeric characters).
  3. Click **Save**.
Test Data: Mobile No = `12345` (too short); Mobile No = `018abcd1234` (non-numeric).
Expected Result: `Assumption:` Save is blocked with a format/length validation message — not verified in this session; confirm actual accepted format with business/dev.

---

### TC-EMP-005: NID/Citizen/Civil/NIN/IDNumber boundary validation
Priority: Medium
Preconditions: Same access as TC-EMP-001.
Test Steps:
  1. Navigate to Employee Create, fill all other required fields validly.
  2. Enter an unusually short/long value in NID.
  3. Click **Save**.
Test Data: NID = `123` (too short).
Expected Result: `Assumption:` Field accepts free-form length (no confirmed min/max) — verify whether the system enforces a specific NID length before treating a failure here as a defect.

---

### TC-EMP-006: Duplicate Mobile No across employees
Priority: High
Preconditions: An employee already exists with a known Mobile No.
Test Steps:
  1. Navigate to Employee Create.
  2. Fill all required fields, reusing the Mobile No of an existing employee.
  3. Click **Save**.
Test Data: Mobile No = an already-registered employee's number.
Expected Result: `Assumption:` System should reject the duplicate with a clear error — uniqueness enforcement not verified in this session; confirm expected behavior with business/dev.

---

### TC-EMP-007: Password / Confirm Password mismatch
Priority: High
Preconditions: Same access as TC-EMP-001.
Test Steps:
  1. Navigate to Employee Create, fill all required Personal Info fields.
  2. Check **User**.
  3. Enter different values in Password and Confirm Password.
  4. Click **Save**.
Test Data: Password = `123456`, Confirm Password = `654321`.
Expected Result: `Assumption:` Save is blocked with a "passwords do not match" validation message — not verified in this session.

---

### TC-EMP-008: User Permission row must be added before it takes effect
Priority: Medium
Preconditions: Same access as TC-EMP-001.
Test Steps:
  1. Navigate to Employee Create, fill required fields, check **User**, fill Password/Confirm Password.
  2. Select Business Unit, Office, Warehouse but do **not** click **Add**.
  3. Click **Save**.
Test Data: Business Unit = `POS App`, Office = `StoreB Head Office`, Warehouse = `StoreB Warehouse One`.
Expected Result: `Assumption:` Employee/user is created, but the Business Unit/Office/Warehouse assignment is not saved because it was never added to the permission table — not explicitly verified; confirm whether Save independently validates this section.

---

### TC-EMP-009: Assign multiple Business Unit/Office/Warehouse permission rows
Priority: Medium
Preconditions: At least two Business Units with distinct Office/Warehouse combinations exist.
Test Steps:
  1. Navigate to Employee Create, fill required fields, check **User**, fill Password/Confirm Password.
  2. Select a Business Unit/Office/Warehouse combination, click **Add**.
  3. Select a second, different Business Unit/Office/Warehouse combination, click **Add**.
  4. Click **Save**.
Test Data: Two distinct Business Unit/Office/Warehouse combinations.
Expected Result: `Assumption:` Both rows are saved and associated with the employee — not verified in this session (only a single row was tested).

---

### TC-EMP-010: Unauthorized user cannot create an employee
Priority: Critical
Preconditions: A user account without Employee-creation permission is available.
Test Steps:
  1. Log in as a user without Employee module access.
  2. Attempt to navigate to Configuration → Entity Master Data → Employee.
Test Data: Restricted-role user credentials.
Expected Result: `Assumption:` Menu item/route is hidden or access is denied — not verified in this session (only tested with a fully authorized account); confirm role/permission model with business/dev.

---

### TC-EMP-011: Newly created employee appears correctly in the Employee list
Priority: High
Preconditions: TC-EMP-001 has been executed.
Test Steps:
  1. After saving, land on the Employee list page.
  2. Locate the newly created employee by Employee Id/Name/Mobile.
  3. Verify list columns (Employee Name, Designation, Office Name, Mobile, Status, etc.) match the entered data.
Test Data: Data from TC-EMP-001.
Expected Result: Employee is listed with Status "Active" and all entered details accurately reflected.

---

### TC-EMP-012: Newly created employee is immediately selectable as Supervisor/Line Manager
Priority: Medium
Preconditions: TC-EMP-001 has been executed.
Test Steps:
  1. Navigate to Employee Create (a second, new employee record).
  2. In the Supervisor field, search for the employee created in TC-EMP-001 by name.
Test Data: Name of the employee created in TC-EMP-001.
Expected Result: `Assumption:` The newly created employee appears in the search results without delay — immediacy not verified in this session.

---

### TC-EMP-013: Employee with a User account can log in to POS App
Priority: High
Preconditions: TC-EMP-001 has been executed with **User** checked.
Test Steps:
  1. Log out of the current session.
  2. Log in using the Mobile No and Password entered in TC-EMP-001.
Test Data: Mobile No / Password from TC-EMP-001.
Expected Result: `Assumption:` Login succeeds and the user lands on the POS App dashboard — not verified in this session (no new-user login was tested).
