import { Link } from "react-router-dom";
import { PageHeader } from "../components/layout/PageHeader";

export function NotFound() {
  return (
    <>
      <PageHeader title="Not found" />
      <p>
        Nothing lives here. <Link to="/">Back to the overview</Link>.
      </p>
    </>
  );
}
