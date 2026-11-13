import { Logo } from "@/components/logo";
import { NavUser } from "@/components/nav-user";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar";

type AppSidebarProps = {
  username: string;
  avatarUrl: string | null;
};

export function AppSidebar({ username, avatarUrl }: AppSidebarProps) {
  return (
    <Sidebar>
      <SidebarHeader>
        <div className="px-2 py-1.5">
          <Logo />
        </div>
      </SidebarHeader>
      <SidebarContent />
      <SidebarFooter>
        <NavUser name={username} avatarUrl={avatarUrl} />
      </SidebarFooter>
    </Sidebar>
  );
}
