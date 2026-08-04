import {
  AppWindowIcon,
  ChevronDownIcon,
  CircleHelpIcon,
  EllipsisVerticalIcon,
  ExternalLinkIcon,
  ServerIcon as LucideServerIcon,
} from "lucide-react";

export const MenuChevron = () => (
  <ChevronDownIcon className="studio-menu-chevron" aria-hidden="true" focusable="false" />
);

export const PopoutIcon = () => (
  <ExternalLinkIcon className="studio-toolbar-icon" aria-hidden="true" />
);

export const MoreIcon = () => (
  <EllipsisVerticalIcon className="studio-toolbar-icon" aria-hidden="true" />
);

export const ServerIcon = () => <LucideServerIcon className="studio-runtime-icon" aria-hidden />;

export const BrowserIcon = () => <AppWindowIcon className="studio-runtime-icon" aria-hidden />;

export const UnknownRuntimeIcon = () => (
  <CircleHelpIcon className="studio-runtime-icon" aria-hidden />
);
