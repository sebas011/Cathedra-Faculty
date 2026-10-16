import type { SVGProps } from "react";

type Props = SVGProps<SVGSVGElement>;
const Icon = ({ children, ...props }: Props) => <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{children}</svg>;

export const DashboardIcon = (p: Props) => <Icon {...p}><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></Icon>;
export const CalendarIcon = (p: Props) => <Icon {...p}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18M7 14h2M12 14h2M7 18h2"/></Icon>;
export const SettingsIcon = (p: Props) => <Icon {...p}><path d="M4 6h7M15 6h5M4 12h3M11 12h9M4 18h10M18 18h2"/><circle cx="13" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="16" cy="18" r="2"/></Icon>;
export const ReportsIcon = (p: Props) => <Icon {...p}><path d="M5 3h10l4 4v14H5zM15 3v4h4"/><path d="M9 17v-3M12 17v-6M15 17v-4"/></Icon>;
export const ReadinessIcon = (p: Props) => <Icon {...p}><path d="M12 3 20 6v6c0 4-3 7-8 9-5-2-8-5-8-9V6z"/><path d="m7.5 12 2.5 0 1.5-3 2.2 6 1.3-3h1.5"/></Icon>;
export const VerificationIcon = (p: Props) => <Icon {...p}><path d="M5 4h12v14H5zM8 8h6M8 12h4"/><circle cx="16.5" cy="16.5" r="3.5"/><path d="m19 19 2 2"/></Icon>;
export const CloseoutIcon = (p: Props) => <Icon {...p}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18m5 5 3 3 5-5"/></Icon>;
export const WorkloadIcon = (p: Props) => <Icon {...p}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></Icon>;
export const DirectoryIcon = (p: Props) => <Icon {...p}><path d="M4 5h16v15H4z"/><path d="M8 9h8M8 13h8M8 17h5"/></Icon>;
export const HistoryIcon = (p: Props) => <Icon {...p}><circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2M4 4l2 2"/></Icon>;
export const HelpIcon = (p: Props) => <Icon {...p}><circle cx="12" cy="12" r="9"/><path d="M9.7 9a2.4 2.4 0 1 1 3.9 1.9c-.9.7-1.6 1.1-1.6 2.5M12 17h.01"/></Icon>;
export const ExpenseIcon = (p: Props) => <Icon {...p}><circle cx="12" cy="12" r="9"/><path d="M15 8.5c-.7-.7-1.7-1-3-1-1.7 0-3 .8-3 2s1 1.8 3 2.2 3 1 3 2.3-1.3 2.2-3 2.2c-1.4 0-2.5-.4-3.2-1.2M12 5.5v13"/></Icon>;
export const BackupIcon = (p: Props) => <Icon {...p}><path d="M4 4h12l4 4v12H4z"/><path d="M8 4v6h8V4M8 20v-6h8v6"/></Icon>;
export const SearchIcon = (p: Props) => <Icon {...p}><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></Icon>;
export const PlusIcon = (p: Props) => <Icon {...p}><path d="M12 5v14M5 12h14"/></Icon>;
export const MenuIcon = (p: Props) => <Icon {...p}><path d="M4 7h16M4 12h16M4 17h16"/></Icon>;
export const UserIcon = (p: Props) => <Icon {...p}><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></Icon>;
export const LogoutIcon = (p: Props) => <Icon {...p}><path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M16 17l5-5-5-5M21 12H9"/></Icon>;
export const EditIcon = (p: Props) => <Icon {...p}><path d="m4 20 4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20Z"/><path d="m14 7 3 3"/></Icon>;
export const TrashIcon = (p: Props) => <Icon {...p}><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></Icon>;
export const ArrowIcon = (p: Props) => <Icon {...p}><path d="M5 12h14M13 6l6 6-6 6"/></Icon>;
