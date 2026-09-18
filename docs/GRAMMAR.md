# The grammar this engine parses

Written the way the parser reads it: loosest precedence first. Anything not
listed here is not supported — the parser says so rather than ignoring it.

```
query      := SELECT [DISTINCT] items FROM table { join }
              [ WHERE expr ]
              [ GROUP BY expr { ',' expr } [ HAVING expr ] ]
              [ ORDER BY order { ',' order } ]
              [ LIMIT integer ] [ OFFSET integer ]

items      := item { ',' item }
item       := '*' | name '.' '*' | expr [ [AS] alias ]

table      := name [ [AS] alias ]
join       := [ INNER | LEFT ] JOIN table ON expr
order      := expr [ ASC | DESC ]

expr       := or
or         := and { OR and }
and        := not { AND not }
not        := NOT not | comparison
comparison := sum [ ( '=' | '<>' | '!=' | '<' | '<=' | '>' | '>=' ) sum
                  | IS [NOT] NULL
                  | [NOT] IN '(' expr { ',' expr } ')'
                  | [NOT] LIKE sum ]
sum        := product { ( '+' | '-' ) product }
product    := unary { ( '*' | '/' | '%' ) unary }
unary      := '-' unary | primary
primary    := number | string | NULL | TRUE | FALSE
            | aggregate | column | '(' expr ')'

aggregate  := ( COUNT '(' '*' ')' )
            | ( COUNT | SUM | AVG | MIN | MAX ) '(' [DISTINCT] expr ')'
column     := name [ '.' name ]
```

## Notes

- **Keywords are case-insensitive; identifiers are not.** `SELECT` and `select`
  are the same word; `Orders` and `orders` are the same table only because table
  lookup is case-insensitive, but a column name must match the header.
- **Strings use single quotes**, and `''` inside one is a literal quote.
- **`--` starts a comment** that runs to the end of the line.
- **`LIMIT` and `OFFSET` take whole numbers only.** `LIMIT 2.5` is an error, not
  a silent truncation.
- **`HAVING` requires `GROUP BY`.** Without one there is no group to filter.
