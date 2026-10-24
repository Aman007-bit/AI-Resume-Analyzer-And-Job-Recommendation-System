import { Link } from 'react-router-dom';
import {
  FileSearch,
  Target,
  Briefcase,
  TrendingUp,
  ArrowRight,
  Sparkles,
  CheckCircle2,
  Upload,
  Zap,
} from 'lucide-react';

const features = [
  {
    icon: FileSearch,
    title: 'Resume Analysis',
    description: 'Upload your resume and get instant AI-powered analysis with a comprehensive skill breakdown.',
    color: 'from-primary-500 to-primary-700',
  },
  {
    icon: Target,
    title: 'Skill Matching',
    description: 'See exactly how your skills align with job requirements — know your strengths and gaps.',
    color: 'from-accent-500 to-accent-700',
  },
  {
    icon: Briefcase,
    title: 'Job Recommendations',
    description: 'Get personalized job recommendations based on your profile and skill match score.',
    color: 'from-success-500 to-success-700',
  },
  {
    icon: TrendingUp,
    title: 'Career Insights',
    description: 'Track your profile strength and discover areas to improve for better job matches.',
    color: 'from-warning-500 to-warning-700',
  },
];

const steps = [
  { icon: Upload, title: 'Upload Your Resume', description: 'PDF or DOCX — we handle the rest.' },
  { icon: Zap, title: 'AI Analyzes Skills', description: 'Instant extraction and scoring.' },
  { icon: CheckCircle2, title: 'Get Matched', description: 'Jobs tailored to your profile.' },
];

export default function HomePage() {
  return (
    <div className="animate-fade-in">
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute left-1/2 top-0 -z-10 h-[500px] w-[800px] -translate-x-1/2 rounded-full bg-primary-100/40 blur-3xl" />

        <div className="mx-auto max-w-7xl px-4 py-20 sm:px-6 lg:px-8 lg:py-28">
          <div className="mx-auto max-w-3xl text-center">
            <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-primary-200 bg-primary-50 px-4 py-1.5 text-sm font-medium text-primary-700">
              <Sparkles className="h-4 w-4" />
              AI-Powered Career Platform
            </div>

            <h1 className="text-balance text-4xl font-extrabold leading-tight text-ink-900 sm:text-5xl lg:text-6xl">
              Land your next job with
              <span className="block bg-gradient-to-r from-primary-600 to-accent-600 bg-clip-text text-transparent">
                smart resume analysis
              </span>
            </h1>

            <p className="mx-auto mt-6 max-w-2xl text-balance text-lg text-ink-500">
              Upload your resume and instantly get skill analysis, match scores, and personalized job recommendations tailored to your profile.
            </p>

            <div className="mt-10 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link to="/signup" className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-6 py-3 text-sm font-semibold text-white hover:bg-blue-700">
                Get Started
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link to="/jobs" className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-6 py-3 text-sm font-semibold text-gray-700 hover:bg-gray-50">
                <Briefcase className="h-4 w-4" />
                View Jobs
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
        <div className="mx-auto mb-12 max-w-2xl text-center">
          <h2 className="text-3xl font-bold text-ink-900 sm:text-4xl">
            Everything you need to land the job
          </h2>
          <p className="mt-4 text-lg text-ink-500">
            Powerful AI tools that analyze your resume and match you with the right opportunities.
          </p>
        </div>

        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((feature, index) => (
            <div
              key={feature.title}
              className="card-hover group p-6"
              style={{ animationDelay: `${index * 80}ms` }}
            >
              <div className={`mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br ${feature.color} shadow-soft`}>
                <feature.icon className="h-6 w-6 text-white" strokeWidth={2} />
              </div>
              <h3 className="text-lg font-semibold text-ink-900">{feature.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-500">
                {feature.description}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className="border-y border-ink-200/60 bg-white py-16 lg:py-20">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto mb-12 max-w-2xl text-center">
            <h2 className="text-3xl font-bold text-ink-900 sm:text-4xl">
              How it works
            </h2>
            <p className="mt-4 text-lg text-ink-500">
              Three simple steps to your next career move.
            </p>
          </div>

          <div className="grid gap-8 md:grid-cols-3">
            {steps.map((step, index) => (
              <div key={step.title} className="relative flex flex-col items-center text-center">
                {index < steps.length - 1 && (
                  <div className="absolute left-[60%] top-8 hidden h-px w-full bg-gradient-to-r from-ink-200 to-transparent md:block" />
                )}
                <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-primary-100 bg-primary-50 shadow-soft">
                  <step.icon className="h-7 w-7 text-primary-600" strokeWidth={2} />
                  <span className="absolute -right-2 -top-2 flex h-6 w-6 items-center justify-center rounded-full bg-primary-600 text-xs font-bold text-white shadow-soft">
                    {index + 1}
                  </span>
                </div>
                <h3 className="mt-4 text-lg font-semibold text-ink-900">{step.title}</h3>
                <p className="mt-1 text-sm text-ink-500">{step.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8 lg:py-20">
        <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-primary-600 to-primary-800 px-8 py-16 text-center shadow-float">
          <div className="relative">
            <h2 className="text-3xl font-bold text-white sm:text-4xl">
              Ready to find your perfect job match?
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-lg text-primary-100">
              Join ResumeAI today and let AI help you land your dream career.
            </p>
            <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                to="/signup"
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-semibold text-primary-700 shadow-soft transition-all hover:shadow-float active:scale-[0.98]"
              >
                Get Started Free
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                to="/login"
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-primary-300/40 bg-primary-500/20 px-6 py-3 text-sm font-semibold text-white backdrop-blur-sm transition-all hover:bg-primary-500/30 active:scale-[0.98]"
              >
                Log in
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
