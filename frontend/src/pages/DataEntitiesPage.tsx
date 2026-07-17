import { useState } from 'react'
import { Database, Plus } from 'lucide-react'
import { useDataEntities } from '../api/dataEntities'
import DataEntityCard from '../components/dataEntities/DataEntityCard'
import DataEntityForm from '../components/dataEntities/DataEntityForm'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Modal from '../components/ui/Modal'
import PageHeader from '../components/ui/PageHeader'
import { CardGridSkeleton } from '../components/ui/Skeleton'
import StatTile from '../components/ui/StatTile'

export default function DataEntitiesPage() {
  const { data: entities, isLoading, error } = useDataEntities()
  const [showForm, setShowForm] = useState(false)

  const mysqlCount = entities?.filter((e) => e.connection.type === 'mysql').length ?? 0
  const mongoCount = entities?.filter((e) => e.connection.type === 'mongo').length ?? 0

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Entities"
        description="The data dictionary a data_query_tool points at — table/collection, columns, labels, and display rules. Describe a table once (or introspect it), reuse it across as many tools as you need."
        actions={
          <Button onClick={() => setShowForm(true)} leftIcon={<Plus size={16} />}>
            New Data Entity
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <StatTile icon={Database} label="Total entities" value={entities?.length ?? 0} tone="brand" />
        <StatTile icon={Database} label="MySQL-backed" value={mysqlCount} tone="neutral" />
        <StatTile icon={Database} label="Mongo-backed" value={mongoCount} tone="success" />
      </div>

      {isLoading && <CardGridSkeleton />}
      {error && <p className="text-sm text-red-600">{(error as Error).message}</p>}
      {!isLoading && !entities?.length && (
        <EmptyState
          icon={Database}
          title="No data entities yet"
          message="Point at a table, introspect or describe its columns, tag a few searchable/filterable — a data_query_tool built from this needs zero hand-written SQL."
          action={
            <Button onClick={() => setShowForm(true)}>
              + New Data Entity
            </Button>
          }
        />
      )}
      {!isLoading && !!entities?.length && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {entities.map((entity) => (
            <DataEntityCard key={entity.id} entity={entity} />
          ))}
        </div>
      )}

      <Modal open={showForm} onClose={() => setShowForm(false)} title="New Data Entity" maxWidth="max-w-3xl">
        <DataEntityForm onDone={() => setShowForm(false)} />
      </Modal>
    </div>
  )
}
