import { useEffect } from "react";
import { pageTitle } from "./credits";

export function usePageTitle(page?: string): void {
  useEffect(() => {
    document.title = pageTitle(page);
  }, [page]);
}
