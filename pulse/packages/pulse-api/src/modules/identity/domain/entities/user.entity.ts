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

@Entity('users')
export class UserEntity {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'uuid', name: 'tenant_id' })
  tenantId!: string;

  @Column({ type: 'varchar', length: 255 })
  email!: string;

  @Column({ type: 'varchar', length: 255 })
  name!: string;

  @Column({ type: 'varchar', length: 512, nullable: true, name: 'avatar_url' })
  avatarUrl!: string | null;

  @Column({ type: 'uuid', name: 'org_id' })
  orgId!: string;

  @ManyToOne(() => OrganizationEntity, (org) => org.users, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'org_id' })
  organization!: OrganizationEntity;

  @Column({ type: 'varchar', length: 50, default: 'member' })
  role!: string;

  @OneToMany(() => MembershipEntity, (membership) => membership.user)
  memberships!: MembershipEntity[];

  @CreateDateColumn({ name: 'created_at', type: 'timestamptz' })
  createdAt!: Date;
}
