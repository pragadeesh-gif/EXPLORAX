POLARIS 2.0 — REALISTIC SIH26062 WORKING MODEL
================================================

Problem Statement:
Integrated Polar Expedition Logistics and Asset Management System

This rebuild is NOT a static dashboard. It is a stateful operational digital-twin prototype with:
- Python backend server
- SQLite database (created automatically)
- login roles
- persistent cargo, shipment, inventory, personnel, asset, work-order, emergency and audit records
- simulation clock
- live vessel movement driven by shipment progress
- inventory consumption over simulation time
- shortage prediction against shipment ETA
- cargo handover/scan history
- cargo registration and rule-based AIR/SHIP recommendation
- mission dependency risk when cargo is delayed
- asset runtime, health and automatic preventive-maintenance work orders
- asset-failure response plan
- emergency resource matching
- weather disruption and ETA propagation
- calculated mission-readiness score
- downloadable cargo manifest CSV
- QR scanning through the browser BarcodeDetector API when supported, with manual cargo-ID fallback

RUN ON WINDOWS
--------------
Easy way:
1. Extract the ZIP.
2. Open the POLARIS_Realistic_Final_Model folder.
3. Double-click run_windows.bat
4. Browser: http://127.0.0.1:8000

PowerShell:
cd "$HOME\Downloads\POLARIS_Realistic_Final_Model"
py app.py

Demo login:
admin / admin123
logistics / log123
station / station123
researcher / res123

BEST SIH DEMO FLOW
------------------
1. Login and show Mission Readiness (calculated from actual database state).
2. Click Run Live or +6h: vessel moves, inventory falls, asset runtime rises.
3. Click Weather Delay: SHP-001 ETA increases; linked cargo becomes delayed; CR-17 can become At Risk; stock forecast is recalculated.
4. Go to Cargo Control and scan PC-1024 at Bharati. The cargo becomes Delivered and its quantity is added to Bharati inventory.
5. Register a new cargo item. The backend chooses AIR/SHIP using priority/weight/category rules and writes the record to SQLite.
6. Simulate GEN-03 failure. The backend finds backup generator, technician and spare stock, then creates a work order.
7. Trigger a medical emergency. The backend matches medical staff, vehicle, medical kit and satellite communications.
8. Open Audit & Reports to prove every change was recorded.

PPT COMPATIBILITY
-----------------
The visible product concept remains POLARIS and the same top-level SIH story remains:
Command Centre + Expedition Planning + Cargo + Inventory + Personnel + Assets + Emergency + Analytics.
So the PPT does not need a new problem statement or a different solution narrative. The rebuild changes the prototype implementation from mock data to real connected workflows.

NOTE
----
This is an SIH prototype/digital twin, not a production system connected to NCPOR operational infrastructure, satellite feeds or real polar-station sensors. External integrations can be added later.
