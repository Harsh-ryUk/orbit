import { IncidentView } from "./view";

export default async function IncidentPage({ params }: PageProps<"/incidents/[id]">) {
  const { id } = await params;
  return <IncidentView id={id} />;
}
