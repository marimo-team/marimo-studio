import { ChevronDownIcon, EllipsisVerticalIcon, ExternalLinkIcon } from "lucide-react";

export const MenuChevron = () => (
  <ChevronDownIcon className="studio-menu-chevron" aria-hidden="true" focusable="false" />
);

export const PopoutIcon = () => (
  <ExternalLinkIcon className="studio-control-icon" aria-hidden="true" />
);

export const MoreIcon = () => (
  <EllipsisVerticalIcon className="studio-control-icon" aria-hidden="true" />
);
