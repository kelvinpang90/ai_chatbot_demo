import { LANGUAGES, type Lang } from '../i18n/strings'

interface Props {
  lang: Lang
  onChange: (lang: Lang) => void
}

export default function LanguageSwitcher({ lang, onChange }: Props) {
  return (
    <div className="lang-switcher">
      {LANGUAGES.map((l) => (
        <button
          key={l.code}
          type="button"
          className={l.code === lang ? 'active' : ''}
          onClick={() => onChange(l.code)}
        >
          {l.label}
        </button>
      ))}
    </div>
  )
}
