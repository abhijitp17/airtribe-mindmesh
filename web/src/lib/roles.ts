// Role landing pages (P3): what a role usually asks for, and a representative job ad that pre-fills
// the gap report, so a visitor only adds their resume. The ads are illustrative, written for Mindmesh
// (fictional companies); the gap report says to paste the real ad for a real application.

export type Role = {
  slug: string;
  title: string;
  summary: string;
  skills: { name: string; why: string }[];
  sampleJob: string;
};

export const ROLES: Role[] = [
  {
    slug: "data-analyst",
    title: "Data Analyst",
    summary: "Turns messy business data into decisions: SQL, a reporting tool, statistics, and clear stories for non-analysts.",
    skills: [
      { name: "SQL", why: "Almost every screen includes a live query exercise." },
      { name: "Dashboards (Tableau or Power BI)", why: "Most roles own recurring reports." },
      { name: "Statistics and A/B testing", why: "You'll be asked to judge whether a change really worked." },
      { name: "Stakeholder communication", why: "Findings only matter if a manager acts on them." },
      { name: "Python or R", why: "Increasingly expected for cleaning and modelling." },
    ],
    sampleJob: `Data Analyst - Commercial Insights
Company: Northwind Retail (example)

Responsibilities
- Build and maintain SQL queries and dashboards that track sales, margin and customer behaviour
- Analyse experiments and promotions, and explain what worked to commercial managers
- Clean and combine data from point-of-sale, web and supplier systems
- Present findings in short, clear written summaries and meetings

Requirements
- 2+ years of experience with SQL
- Experience with Tableau or Power BI
- Solid statistics, including A/B testing and significance
- Strong communication with non-technical stakeholders

Preferred
- Python or R for data cleaning and modelling
- Retail or e-commerce domain knowledge`,
  },
  {
    slug: "product-manager",
    title: "Product Manager",
    summary: "Decides what to build and why: discovery with users, prioritisation, working with engineers and design, and measuring outcomes.",
    skills: [
      { name: "Product discovery and user research", why: "Interviewers probe how you find real problems." },
      { name: "Prioritisation", why: "Expect a 'what would you cut?' case." },
      { name: "Metrics and experimentation", why: "You'll define success and read an A/B test." },
      { name: "Working with engineering", why: "Trade-offs, scope and delivery come up in every loop." },
      { name: "Written communication", why: "Specs and decision documents are the job." },
    ],
    sampleJob: `Product Manager - Growth
Company: Fabrikam Apps (example)

Responsibilities
- Own the onboarding and activation funnel for a consumer mobile app
- Run discovery: user interviews, funnel analysis and competitive research
- Prioritise a roadmap with engineering and design, and write clear specifications
- Define success metrics, design experiments and report on outcomes

Requirements
- 3+ years of product management experience
- Experience running A/B tests and interpreting results
- Strong prioritisation and stakeholder management skills
- Excellent written and verbal communication

Preferred
- Experience with mobile products
- Basic SQL to answer your own questions`,
  },
  {
    slug: "software-engineer",
    title: "Software Engineer",
    summary: "Builds and runs software: data structures and algorithms, system design, code quality, and working in a team.",
    skills: [
      { name: "Data structures and algorithms", why: "Coding rounds still lead most loops." },
      { name: "System design", why: "Expected from mid-level up: APIs, data stores, scaling." },
      { name: "Testing and code quality", why: "Reviewers look for tests and readable code." },
      { name: "Debugging production issues", why: "Behavioural rounds ask for a real incident story." },
      { name: "Collaboration", why: "Code review and design discussions are daily work." },
    ],
    sampleJob: `Software Engineer - Backend
Company: Contoso Payments (example)

Responsibilities
- Design, build and operate backend services and APIs in Python or Go
- Write well-tested, maintainable code and review your teammates' changes
- Improve reliability: monitoring, alerting and incident follow-ups
- Work with product and design to scope and deliver features

Requirements
- 3+ years of professional software engineering experience
- Strong grasp of data structures, algorithms and system design
- Experience with relational databases and SQL
- Experience with automated testing and CI

Preferred
- Experience with distributed systems or payments
- Familiarity with cloud infrastructure and containers`,
  },
  {
    slug: "operations-manager",
    title: "Operations Manager",
    summary: "Keeps work flowing: capacity, bottlenecks, inventory, process improvement, and leading a team.",
    skills: [
      { name: "Capacity and bottleneck analysis", why: "Expect a case on where a process is stuck." },
      { name: "Inventory management", why: "Safety stock and reorder points come up often." },
      { name: "Lean and process improvement", why: "Interviewers want concrete before-and-after results." },
      { name: "People leadership", why: "You'll be asked how you run a team and handle conflict." },
      { name: "KPIs and reporting", why: "You own the numbers for your area." },
    ],
    sampleJob: `Operations Manager - Fulfilment
Company: Fabrikam Foods (example)

Responsibilities
- Run daily fulfilment operations for a regional warehouse and a team of twelve
- Plan capacity and staffing, and remove bottlenecks in picking and packing
- Set inventory policies with procurement, including safety stock and reorder points
- Lead continuous improvement using lean methods and track KPIs

Requirements
- 4+ years in operations or supply chain, including people management
- Experience with capacity planning and process improvement
- Working knowledge of inventory management
- Strong communication and problem-solving skills

Preferred
- Lean or Six Sigma certification
- Experience with warehouse management systems`,
  },
  {
    slug: "financial-analyst",
    title: "Financial Analyst",
    summary: "Explains the numbers: financial modelling, valuation, working capital and clear recommendations to leadership.",
    skills: [
      { name: "Financial modelling in Excel", why: "Most loops include a modelling test." },
      { name: "Valuation (NPV, IRR, WACC)", why: "Expect questions on discounting and cost of capital." },
      { name: "Working capital and cash flow", why: "Interviewers test how cash really moves." },
      { name: "Budgeting and forecasting", why: "Planning cycles are the core of the role." },
      { name: "Presenting to leadership", why: "Your analysis has to land in a short deck." },
    ],
    sampleJob: `Financial Analyst - FP&A
Company: Contoso Manufacturing (example)

Responsibilities
- Build and maintain the annual budget and monthly forecasts
- Analyse performance against plan and explain variances to business leaders
- Evaluate investment proposals using NPV, IRR and payback
- Track working capital and the cash conversion cycle

Requirements
- 2+ years in FP&A, corporate finance or audit
- Advanced Excel and financial modelling
- Solid understanding of valuation and the cost of capital
- Clear written and verbal communication

Preferred
- CFA, CIMA or ACCA progress
- Experience with a planning tool such as Anaplan`,
  },
];

export const roleBySlug = (slug: string | null | undefined): Role | undefined => ROLES.find((r) => r.slug === slug);
