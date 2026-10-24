// Fictional resume and job ad (example.com address, reserved test phone number),
// copied from backend/tests/test_interview_samples.py so the mock parser handles them.

export const SAMPLE_RESUME = `Priya Sharma
priya.sharma@example.com | +44 7700 900123 | London, UK

Summary
Data analyst with five years of experience turning messy operational data into decisions.

Experience
Senior Data Analyst | Northwind Retail | Mar 2022 - Present
• Improved demand forecast accuracy by 8% by replacing a moving-average model with gradient boosting in Python
• Built SQL pipelines in BigQuery that feed weekly sales dashboards used by 40 store managers
• Led a cross-functional pricing review with finance and merchandising stakeholders, presenting findings to the leadership team
• Mentored two junior analysts on SQL and dashboard design

Data Analyst | Contoso Logistics | Jun 2019 - Feb 2022
• Reduced reporting time from 3 days to 4 hours by automating Excel reports with Python
• Designed an A/B test framework to evaluate warehouse slotting changes
• Analysed delivery delays and presented recommendations to operations managers

Skills
Python, SQL, Tableau, Excel, Statistics, Machine Learning, Forecasting

Education
BSc Mathematics, University of Leeds, 2019
`;

export const SAMPLE_JD = `Analytics Manager - Supply Chain
Company: Fabrikam Foods

About the role
Fabrikam Foods is looking for an Analytics Manager to lead our supply chain analytics team.

Responsibilities
- Lead a team of four analysts and set analytics priorities with supply chain leadership
- Build demand forecasting models that drive inventory decisions
- Communicate insights to senior stakeholders in clear, concise presentations

Requirements
- 5+ years of experience with SQL and Python
- Strong experience with demand forecasting and statistical modelling
- Proven people management experience
- Excellent stakeholder management and communication skills
- Must have experience with A/B testing and experiment design

Preferred
- Experience with Tableau or Power BI
- Supply chain domain knowledge
`;

export const SAMPLE_PDF = "e2e/fixtures/factory-physics-sample.pdf";

export const uniqueEmail = (tag: string) => `e2e-${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
export const PASSWORD = "correct-horse-1";
