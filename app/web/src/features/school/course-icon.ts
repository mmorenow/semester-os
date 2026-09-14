import {
  Atom,
  BookOpen,
  Calculator,
  Flask,
  Globe,
  GraduationCap,
  Notebook,
  type Icon,
} from '@phosphor-icons/react'

import { COURSE_SLOTS } from './course-color'

/**
 * One glyph per course slot, paired with the slot's color. Identity, not subject.
 * No slot gets `GraduationCap`; never hash from a name, so the mark is stable everywhere.
 */
const ICONS: Icon[] = [BookOpen, Notebook, Calculator, Flask, Atom, Globe]

/** The glyph for a course slot, or the category glyph when there is no slot. */
export function courseIcon(slot: number | undefined): Icon {
  return slot === undefined ? GraduationCap : ICONS[slot % COURSE_SLOTS]
}
