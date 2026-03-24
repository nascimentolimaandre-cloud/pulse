import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  ManyToOne,
  JoinColumn,
} from 'typeorm';
import { UserEntity } from './user.entity';
import { TeamEntity } from './team.entity';

@Entity('memberships')
export class MembershipEntity {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column({ type: 'uuid', name: 'tenant_id' })
  tenantId!: string;

  @Column({ type: 'uuid', name: 'user_id' })
  userId!: string;

  @ManyToOne(() => UserEntity, (user) => user.memberships, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'user_id' })
  user!: UserEntity;

  @Column({ type: 'uuid', name: 'team_id' })
  teamId!: string;

  @ManyToOne(() => TeamEntity, (team) => team.memberships, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'team_id' })
  team!: TeamEntity;

  @Column({ type: 'varchar', length: 50, default: 'member' })
  role!: string;

  @CreateDateColumn({ name: 'created_at', type: 'timestamptz' })
  createdAt!: Date;
}
