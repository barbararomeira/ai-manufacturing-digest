# Notion tag cleanup

Collapses the accumulated options onto the reduced vocabulary the pipeline now uses:
**11 Categories** and **13 Industries**.

**How to merge in Notion:** open the property's option list and rename the option
shown to exactly match the bold heading above it. Notion merges the two and rewrites
every row that used it. Work top to bottom within a group.

Generated from the same `snap_tags()` logic the pipeline uses, so the cleanup and all
future rows agree.


---

## Category: 66 options -> 11 (41 merges)

### AI Infrastructure
- rename `data_collection`
- rename `Data Management`
- rename `edge computing`

### Computer Vision
- rename `computer_vision`
- rename `computer vision`

### Cybersecurity
- rename `Threat Detection`

### Energy Management
- rename `energy management`

### Predictive Maintenance
- rename `predictive_maintenance`
- rename `asset_management`

### Process Optimization
- rename `process optimization`
- rename `efficiency`
- rename `production scaling`
- rename `operational efficiency`
- rename `process_optimization`
- rename `production_planning`
- rename `cost reduction`
- rename `Production Optimization`
- rename `labor optimization`

### Quality & Inspection
- rename `Quality Control`
- rename `quality_control`
- rename `defect detection`
- rename `autonomous inspection`

### Robotics & Automation
- rename `Automation`
- rename `robotic automation`
- rename `robotics`
- rename `material_handling`
- rename `Autonomous Systems`
- rename `process_automation`
- rename `autonomous robotics`
- rename `precision assembly`
- rename `Collaborative Robotics`
- rename `robotic process automation`
- rename `autonomous vehicles`
- rename `industrial_automation`
- rename `autonomous robots`
- rename `cognitive robotics`
- rename `Process Automation`
- rename `swarm intelligence`

### Simulation & Digital Twin
- rename `Generative Design`
- rename `design optimization`
- rename `simulation`

### Supply Chain & Logistics
- rename `Warehouse Automation`
- rename `logistics automation`
- rename `supply chain`
- rename `supply_chain_optimization`
- rename `warehouse_automation`

### Workforce & Safety
- rename `workforce`
- rename `AI Assistant`
- rename `workforce development`
- rename `Human-Machine Interaction`
- rename `Human-Robot Collaboration`

### Category: retired — no replacement

Mostly technique names and vague catch-alls. New rows will never use them, so
delete them once no row depends on them, or leave them as historical labels.

- `AI in Manufacturing`
- `Smart Manufacturing`
- `predictive analytics`
- `custom manufacturing`
- `AI Adoption`
- `Research & Development`
- `micromanufacturing`
- `natural language processing`
- `knowledge management`
- `explainable AI (XAI)`
- `predictive_analytics`
- `machine_learning`
- `Machine Learning`
- `adaptive manufacturing`

---

## Industry: 51 options -> 13 (33 merges)

### Aerospace & Defense
- rename `shipbuilding`
- rename `aerospace manufacturing`
- rename `aerospace`
- rename `defense`

### Automotive
- rename `automotive`
- rename `Automotive Manufacturing`
- rename `Electric Vehicles`

### Chemicals
- rename `chemical manufacturing`

### Construction
- rename `construction`

### Consumer Goods
- rename `furniture manufacturing`
- rename `furniture`
- rename `fast-moving consumer goods`

### Electronics & Semiconductors
- rename `Electronics`
- rename `Electronics Manufacturing`
- rename `Semiconductor Manufacturing`
- rename `semiconductors`
- rename `semiconductors and electronics`
- rename `consumer electronics`

### Energy & Utilities
- rename `energy`
- rename `utilities`
- rename `Water Treatment`

### Food & Beverage
- rename `food manufacturing`
- rename `food and beverage`
- rename `food and consumer goods`

### General Manufacturing
- rename `Manufacturing`
- rename `Custom Manufacturing`
- rename `custom fabrication`
- rename `general manufacturing`
- rename `industrial manufacturing`

### Industrial Equipment
- rename `industrial automation`
- rename `Robotics`
- rename `industrial_equipment`
- rename `industrial_automation`

### Logistics & Warehousing
- rename `e_commerce`
- rename `Logistics`
- rename `warehousing`
- rename `industrial logistics`

### Metals & Mining
- rename `mining`

### Pharma & Medical
- rename `pharmaceutical_manufacturing`
- rename `biotech`
- rename `Pharmaceuticals`
- rename `medical`
- rename `Medical Devices`
- rename `healthcare`
- rename `life sciences`

### Industry: retired — no replacement

Mostly technique names and vague catch-alls. New rows will never use them, so
delete them once no row depends on them, or leave them as historical labels.

- `india`
- `Technology`
- `finance`
- `supply_chain_management`
- `AI Infrastructure`
