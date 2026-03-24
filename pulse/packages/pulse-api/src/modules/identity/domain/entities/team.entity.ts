import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  ManyToOne,
  JoinColumn,
  OneToMany,
} from 'typeorm';
import { OrganizationEntity } from './organization.entity';
import { MembershipEntity } from './membership.entity';

@Entity('teams')
export class TeamEntity {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'uuid', name: 'tenant_id' })
  tenantId!: string;

  @Column({ type: 'varchar', length: 255 })
  name!: string;

  @Column({ type: 'uuid', name: 'org_id' })
  orgId!: string;

  @ManyToOne(() => OrganizationEntity, (org) => org.teams, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'org_id' })
  organization!: OrganizationEntity;

  @Column({ type: 'jsonb', name: 'repo_ids', default: '[]' })
  repoIds!: string[];

  @Column({ type: 'jsonb', name: 'board_config', default: '{}' })
  boardConfig!: Record<string, unknown>;

  @OneToMany(() => MembershipEntity, (membership) => membership.team)
  memberships!: MembershipEntity[];

  @CreateDateColumn({ name: 'created_at', type: 'timestamptz' })
  createdAt!: Date;
}
