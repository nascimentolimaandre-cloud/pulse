import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  UpdateDateColumn,
} from 'typeorm';

export type SourceType = 'github' | 'gitlab' | 'jira' | 'azure_devops' | 'jenkins';
export type ConnectionStatus = 'active' | 'inactive' | 'error' | 'pending';

@Entity('connections')
export class ConnectionEntity {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'uuid', name: 'tenant_id' })
  tenantId!: string;

  @Column({ type: 'uuid', name: 'org_id' })
  orgId!: string;

  @Column({
    type: 'varchar',
    length: 50,
    name: 'source_type',
  })
  sourceType!: SourceType;

  @Column({ type: 'jsonb', default: '{}' })
  config!: Record<string, unknown>;

  @Column({
    type: 'varchar',
    length: 20,
    default: 'pending',
  })
  status!: ConnectionStatus;

  @Column({
    type: 'timestamptz',
    nullable: true,
    name: 'last_sync_at',
  })
  lastSyncAt!: Date | null;

  @CreateDateColumn({ name: 'created_at', type: 'timestamptz' })
  createdAt!: Date;

  @UpdateDateColumn({ name: 'updated_at', type: 'timestamptz' })
  updatedAt!: Date;
}
