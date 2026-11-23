import { NavLink, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { HeaderDropdown } from './HeaderDropdown'
import { useAuth } from './AuthProvider'
import { ThemeToggle } from './ThemeToggle'
import './UserMenu.css'

const MENU_LINKS: { to: string; labelKey: string; superuserOnly?: boolean }[] = [
  { to: '/status', labelKey: 'status' },
  { to: '/remote-configuration', labelKey: 'remoteConfiguration', superuserOnly: true },
  { to: '/runs', labelKey: 'runs' },
  { to: '/admin/campaigns', labelKey: 'campaigns', superuserOnly: true },
  { to: '/testing/visualization', labelKey: 'testing', superuserOnly: true },
  { to: '/admin/users', labelKey: 'users', superuserOnly: true },
  { to: '/change-password', labelKey: 'changePassword' },
  { to: '/settings', labelKey: 'settings' },
]

export function UserMenu() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { t } = useTranslation('shell')
  const menuLinks = MENU_LINKS.filter((link) => !link.superuserOnly || user?.is_superuser)

  return (
    <HeaderDropdown
      trigger={({ toggle, isOpen }) => (
        <button
          type="button"
          className="user-menu__trigger"
          onClick={toggle}
          aria-expanded={isOpen}
          aria-label={t('openUserMenu')}
        >
          <span className="user-menu__hamburger" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span>{user?.email}</span>
        </button>
      )}
    >
      {({ close }) => (
        <nav className="user-menu__panel">
          {menuLinks.map(({ to, labelKey }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => (isActive ? 'active' : undefined)}
              onClick={close}
            >
              {t(`menu.${labelKey}`)}
            </NavLink>
          ))}
          <button
            type="button"
            className="user-menu__logout"
            onClick={() => {
              close()
              logout()
              navigate('/map')
            }}
          >
            {t('logout')}
          </button>
          <ThemeToggle />
        </nav>
      )}
    </HeaderDropdown>
  )
}
