/** Only constructed by the client's completed, pre-fetch placement guards. */
export class OrderPreflightRefusal extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OrderPreflightRefusal";
  }
}
