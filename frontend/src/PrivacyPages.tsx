import { type ReactNode } from 'react'
import { ArrowLeft, ShieldCheck } from 'lucide-react'

export type StorageConsent = 'all' | 'essential'
export type LegalPageKind = 'privacy' | 'cookies'

type PrivacyPolicyPageProps = {
  onBack: () => void
  onOpenCookies: () => void
}

type StoragePreferencesPageProps = {
  consent: StorageConsent | null
  onBack: () => void
  onChoose: (choice: StorageConsent) => void
}

type CookieConsentBannerProps = {
  consent: StorageConsent | null
  onChoose: (choice: StorageConsent) => void
  onManage: () => void
}

function LegalPageFrame({ children, onBack }: { children: ReactNode; onBack: () => void }) {
  return (
    <main className="legal-page">
      <header className="legal-header">
        <a className="brand" href="#" onClick={(event) => { event.preventDefault(); onBack() }}>
          <span className="brand-mark">U</span>
          <span className="brand-copy"><strong>urbannest</strong><small>Realty CRM</small></span>
        </a>
        <button className="button button-secondary" onClick={onBack}><ArrowLeft size={16} /> Back</button>
      </header>
      <div className="legal-content">{children}</div>
      <footer className="legal-page-footer">UrbanNest Realty CRM</footer>
    </main>
  )
}

export function PrivacyPolicyPage({ onBack, onOpenCookies }: PrivacyPolicyPageProps) {
  return (
    <LegalPageFrame onBack={onBack}>
      <article className="legal-card">
        <p className="eyebrow">Privacy &amp; data</p>
        <h1>Privacy policy</h1>
        <p className="legal-updated">Effective date: November 14, 2026</p>
        <div className="legal-notice" role="note">
          This policy needs the bracketed operator and contact details completed and should be reviewed for the
          jurisdictions where UrbanNest is offered before production use.
        </div>

        <section>
          <h2>Who operates UrbanNest</h2>
          <p>
            UrbanNest Realty CRM is operated by <strong>[insert the legal name of the operating entity]</strong>.
            Privacy questions and requests can be sent to <strong>[insert privacy contact email and postal address]</strong>.
            The service operator is responsible for confirming the applicable legal basis, jurisdiction-specific rights,
            and deployment details for its use of the CRM.
          </p>
        </section>

        <section>
          <h2>Information handled by the service</h2>
          <ul>
            <li>Workspace account details such as name, email address, optional phone number, role, and team.</li>
            <li>Lead details entered by a workspace, which may include name, email, phone, property preferences, budget, location, and notes.</li>
            <li>Follow-up tasks, activity entries, pipeline changes, and security or audit events.</li>
            <li>Authentication and operational data needed to secure accounts, such as token and login-limit metadata.</li>
            <li>When an AI feature is enabled, lead context and recent activity needed to produce the requested suggestion.</li>
          </ul>
          <p>
            The application stores CRM records in the database configured by the service operator. Do not enter real
            client information into a demo or test workspace.
          </p>
        </section>

        <section>
          <h2>How information is used</h2>
          <p>
            Workspace data is used to provide sign-in, role-based CRM access, lead and follow-up workflows, activity
            history, team administration, and service security. When requested, AI features may use lead context to
            create a score, draft, or extraction suggestion. Review generated content before relying on or sharing it.
          </p>
        </section>

        <section>
          <h2>AI and service providers</h2>
          <p>
            If AI assistance is enabled, the configured provider may be Google Gemini or an operator-managed Ollama
            server. AI prompts can include a lead's name, source, status, budget, location, notes, and recent activity;
            email and phone fields are excluded by the current application. Provider, model, usage, latency, outcome,
            and request identifiers may be recorded as metadata. The application does not store AI prompts or
            completions, but provider-side handling depends on the selected provider and its terms.
          </p>
          <p>
            Hosting, database, email, backup, and AI provider details are selected by the operator. Complete
            <strong> [insert provider names, processing locations, and relevant links]</strong> for the production deployment.
          </p>
        </section>

        <section>
          <h2>Browser storage and cookies</h2>
          <p>
            The application keeps the sign-in token in tab-scoped session storage. If you allow optional preferences,
            first-party cookies remember the selected theme and collapsed-sidebar setting. A first-party cookie
            remembers your storage choice. The application does not use advertising cookies or trackers.
          </p>
          <button className="text-button legal-action" onClick={onOpenCookies}>Review cookie and storage choices</button>
        </section>

        <section>
          <h2>Retention and security</h2>
          <p>
            Passwords are stored as hashes, not readable passwords. The application does not implement an automatic
            user-data deletion or retention schedule. The operator must define retention, backups, access controls,
            incident handling, and deletion procedures for the database and any configured providers.
          </p>
        </section>

        <section>
          <h2>Your choices and requests</h2>
          <p>
            Contact the workspace operator using the details above to ask about access, correction, export, deletion,
            or other rights available under the laws that apply to you. The operator should verify the request and
            respond according to its legal obligations and retention requirements.
          </p>
        </section>

        <section>
          <h2>Changes to this policy</h2>
          <p>
            The operator should update this page when data handling or providers change and publish the effective date
            of each revision.
          </p>
        </section>
      </article>
    </LegalPageFrame>
  )
}

export function StoragePreferencesPage({ consent, onBack, onChoose }: StoragePreferencesPageProps) {
  return (
    <LegalPageFrame onBack={onBack}>
      <article className="legal-card">
        <p className="eyebrow">Privacy &amp; browser storage</p>
        <h1>Cookie and storage choices</h1>
        <p className="legal-lead">UrbanNest uses first-party cookies for your storage choice and, if enabled, display preferences. It does not use advertising cookies or trackers.</p>
        <section>
          <h2>Required for the workspace</h2>
          <p>
            Session storage keeps your sign-in token in the current browser tab. A first-party cookie remembers your
            storage choice so the app can apply it when you return.
          </p>
        </section>
        <section>
          <h2>Optional display preferences</h2>
          <p>
            If enabled, first-party cookies remember your light or dark theme and whether the sidebar is collapsed.
            Choosing essential storage only removes those preference cookies; theme and sidebar controls still work
            until the current tab is closed.
          </p>
        </section>
        <div className="storage-choice-summary" role="status">
          <ShieldCheck size={18} />
          <span>
            Current choice: <strong>{consent === 'all' ? 'Optional display preferences enabled' : consent === 'essential' ? 'Essential storage only' : 'No choice saved yet'}</strong>
          </span>
        </div>
        <div className="storage-choice-actions">
          <button className="button button-primary" onClick={() => onChoose('all')}>Allow display preferences</button>
          <button className="button button-secondary" onClick={() => onChoose('essential')}>Use essential only</button>
        </div>
        <p className="legal-footnote">
          These controls describe the browser storage used by this application. They do not control storage used by
          your organization's hosting, database, email, or AI providers.
        </p>
      </article>
    </LegalPageFrame>
  )
}

export function CookieConsentBanner({ consent, onChoose, onManage }: CookieConsentBannerProps) {
  if (consent !== null) {
    return null
  }

  return (
    <aside className="cookie-consent-banner" role="region" aria-label="Privacy choices">
      <div>
        <strong>Your browser storage choices</strong>
        <p>Sign-in uses session storage. Optional display preferences are saved as first-party cookies only if you allow them; this app does not use advertising cookies.</p>
        <button className="text-button" onClick={onManage}>Details and choices</button>
      </div>
      <div className="cookie-consent-actions">
        <button className="button button-secondary" onClick={() => onChoose('essential')}>Essential only</button>
        <button className="button button-primary" onClick={() => onChoose('all')}>Allow preferences</button>
      </div>
    </aside>
  )
}
