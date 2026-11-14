import { Link } from "@tanstack/react-router";
import { Shirt, Sparkles } from "lucide-react";

import { Logo } from "@/components/logo";
import { NavUser } from "@/components/nav-user";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

type AppSection = "recomendaciones" | "wardrobe";

type AppSidebarProps = {
  username: string;
  avatarUrl: string | null;
  section: AppSection;
};

export function AppSidebar({ username, avatarUrl, section }: AppSidebarProps) {
  return (
    <Sidebar>
      <SidebarHeader>
        <div className="px-2 py-1.5">
          <Logo />
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={section === "recomendaciones"}
                  render={<Link to="/recomendar/$username" params={{ username }} />}
                >
                  <Sparkles />
                  <span>Recomendaciones</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={section === "wardrobe"}
                  render={<Link to="/wardrobe/$username" params={{ username }} />}
                >
                  <Shirt />
                  <span>Wardrobe</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        <NavUser name={username} avatarUrl={avatarUrl} />
      </SidebarFooter>
    </Sidebar>
  );
}
