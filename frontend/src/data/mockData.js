/* ==========================================================================
   TEMPORARY FRONTEND MOCK DATA
   --------------------------------------------------------------------------
   This file exists ONLY because the backend does not exist yet.
   Nothing in the UI imports this file directly — components talk to the
   functions in src/services/*, and those functions are the only code that
   reads from here. When the FastAPI backend is ready, the services switch to
   real requests and this whole file can be deleted.

   All people, scores and numbers below are made-up development data.
   ========================================================================== */

/* ---------- Jobs (shape = what the backend will return) ------------------- */
export const mockJobs = [
  {
    id: 1,
    title: 'Backend Developer',
    company: 'TCS',
    location: 'Bangalore',
    employmentType: 'Full-time',
    experience: '2-4 years',
    matchScore: 86,
    matchedSkills: ['Java', 'Spring Boot', 'MySQL', 'REST API'],
    missingSkills: ['Docker', 'Microservices', 'AWS'],
    description:
      'We are looking for a Backend Developer to join our team. You will be responsible for building scalable backend services, working with databases, and collaborating with cross-functional teams.',
    requirements: [
      'Strong knowledge of Java and Spring Boot',
      'Experience with REST API development',
      'Good understanding of MySQL',
      'Familiarity with microservices architecture (preferred)',
      'Knowledge of Docker and cloud platforms (preferred)',
    ],
    applyUrl: 'https://www.tcs.com/careers',
  },
  {
    id: 2,
    title: 'Java Developer',
    company: 'Infosys',
    location: 'Pune',
    employmentType: 'Full-time',
    experience: '1-3 years',
    matchScore: 82,
    matchedSkills: ['Java', 'Spring Boot', 'SQL'],
    missingSkills: ['Microservices'],
    description:
      'Join our delivery team to design, develop and maintain Java applications for enterprise clients. You will write clean, testable code and take part in code reviews and sprint planning.',
    requirements: [
      'Solid understanding of core Java and object-oriented design',
      'Hands-on experience with Spring Boot',
      'Working knowledge of SQL and relational databases',
      'Exposure to microservices (preferred)',
      'Good communication skills and willingness to learn',
    ],
    applyUrl: 'https://www.infosys.com/careers',
  },
  {
    id: 3,
    title: 'Full Stack Developer',
    company: 'Wipro',
    location: 'Bangalore',
    employmentType: 'Full-time',
    experience: '2-5 years',
    matchScore: 78,
    matchedSkills: ['Java', 'React', 'MySQL', 'Spring Boot'],
    missingSkills: ['Docker', 'AWS'],
    description:
      'We need a Full Stack Developer who is comfortable working on both the user interface and the services behind it. You will build features end to end, from React screens to Java APIs and database design.',
    requirements: [
      'Experience building user interfaces with React',
      'Backend development with Java and Spring Boot',
      'Database design and queries in MySQL',
      'Understanding of CI/CD and containers (preferred)',
      'Familiarity with a cloud provider such as AWS (preferred)',
    ],
    applyUrl: 'https://careers.wipro.com',
  },
  {
    id: 4,
    title: 'Software Engineer',
    company: 'Accenture',
    location: 'Gurgaon',
    employmentType: 'Full-time',
    experience: '1-3 years',
    matchScore: 74,
    matchedSkills: ['Java', 'SQL', 'REST API'],
    missingSkills: ['Docker'],
    description:
      'As a Software Engineer you will develop and support client applications, work with business analysts to refine requirements, and deliver reliable features in an agile team.',
    requirements: [
      'Programming experience in Java or a similar language',
      'Knowledge of SQL and REST APIs',
      'Understanding of the software development life cycle',
      'Basic knowledge of Docker (preferred)',
      'Strong problem-solving skills',
    ],
    applyUrl: 'https://www.accenture.com/in-en/careers',
  },
  {
    id: 5,
    title: 'React Developer',
    company: 'Cognizant',
    location: 'Chennai',
    employmentType: 'Full-time',
    experience: '1-3 years',
    matchScore: 71,
    matchedSkills: ['React', 'JavaScript', 'HTML', 'CSS'],
    missingSkills: ['TypeScript', 'Jest'],
    description:
      'Build responsive, accessible web interfaces for enterprise products. You will turn designs into reusable React components and work closely with backend engineers to integrate APIs.',
    requirements: [
      'Strong JavaScript and React fundamentals',
      'Good command of HTML and CSS',
      'Experience consuming REST APIs',
      'TypeScript experience (preferred)',
      'Unit testing with Jest (preferred)',
    ],
    applyUrl: 'https://careers.cognizant.com',
  },
  {
    id: 6,
    title: 'Associate Software Engineer',
    company: 'HCLTech',
    location: 'Noida',
    employmentType: 'Full-time',
    experience: '0-2 years',
    matchScore: 69,
    matchedSkills: ['Java', 'SQL', 'Git'],
    missingSkills: ['Linux', 'Docker'],
    description:
      'An entry-level role for graduates who want to grow into full-time engineering. You will be mentored by senior developers while contributing to real customer projects.',
    requirements: [
      'Degree in Computer Science or a related field',
      'Good understanding of Java and data structures',
      'Basic SQL and version control with Git',
      'Familiarity with Linux (preferred)',
      'Eagerness to learn new technologies',
    ],
    applyUrl: 'https://www.hcltech.com/careers',
  },
  {
    id: 7,
    title: 'Software Engineering Intern',
    company: 'Tech Mahindra',
    location: 'Hyderabad',
    employmentType: 'Internship',
    experience: '0-1 years',
    matchScore: 66,
    matchedSkills: ['JavaScript', 'HTML', 'CSS', 'Git'],
    missingSkills: ['Node.js'],
    description:
      'A six-month internship working with a product team on web applications. You will fix bugs, build small features and learn how production software is shipped.',
    requirements: [
      'Currently pursuing or recently completed a technical degree',
      'Basic JavaScript, HTML and CSS',
      'Comfort with Git workflows',
      'Interest in Node.js and backend development',
    ],
    applyUrl: 'https://careers.techmahindra.com',
  },
  {
    id: 8,
    title: 'Java Backend Engineer',
    company: 'LTIMindtree',
    location: 'Mumbai',
    employmentType: 'Contract',
    experience: '2-4 years',
    matchScore: 63,
    matchedSkills: ['Java', 'Spring Boot', 'MySQL'],
    missingSkills: ['Kafka', 'Microservices', 'AWS'],
    description:
      'A 12-month contract to help modernise a set of backend services. You will extend existing Spring Boot services and take part in the migration to a service-oriented architecture.',
    requirements: [
      'Proven experience with Java and Spring Boot',
      'Good knowledge of MySQL',
      'Experience with message queues such as Kafka (preferred)',
      'Cloud experience with AWS (preferred)',
    ],
    // Intentionally empty: lets the UI show the "no apply link" state.
    applyUrl: null,
  },
]

/* ---------- Logged-in user's profile (as the resume analysis would give) -- */
export const mockUserProfile = {
  name: 'Aman',
  education: {
    degree: 'B.Tech in Computer Science',
    institution: 'Galgotias University',
    years: '2022 - 2026',
  },
  skills: [
    'Java',
    'Spring Boot',
    'MySQL',
    'React',
    'HTML',
    'CSS',
    'JavaScript',
    'SQL',
    'REST API',
    'Git',
    'Python',
    'Data Structures',
  ],
  profileMatch: 86,
  matchedSkills: ['Java', 'Spring Boot', 'MySQL', 'REST API', 'React', 'JavaScript', 'SQL', 'Git'],
  missingSkills: ['Docker', 'Microservices', 'AWS', 'TypeScript', 'Kafka'],
  // Placeholder for the future LLM-generated career / learning advice.
  suggestions: [
    {
      id: 1,
      title: 'Learn Docker',
      description:
        'Most of the backend roles matching your profile ask for containers. Start by containerising one of your Spring Boot projects.',
    },
    {
      id: 2,
      title: 'Build a small microservices project',
      description:
        'Split an existing project into two services that talk over REST. It gives you a concrete example for interviews.',
    },
    {
      id: 3,
      title: 'Get started with AWS basics',
      description:
        'Cloud foundations (compute, storage, IAM) appear in the preferred requirements of several of your top matches.',
    },
    {
      id: 4,
      title: 'Add measurable results to your projects',
      description:
        'Mention numbers such as users, response times or test coverage in your resume project descriptions.',
    },
  ],
}

/* ---------- Public marketing numbers shown on the Home page --------------- */
export const mockPlatformStats = [
  { id: 'jobs', value: '10K+', label: 'Job Listings' },
  { id: 'relevance', value: '90%', label: 'Relevant Matches' },
  { id: 'students', value: '5K+', label: 'Students Use' },
]
